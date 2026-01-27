"""
Christina Call Notes - Combined Bot Server + Processor
Runs the bot web server and the PDF processor in the same process.
"""

import os
import asyncio
import threading
import time
import logging

# Set up logging first
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import the processor module
import call_notes_processor as processor

# Bot server imports
import json
from aiohttp import web
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, ActivityTypes, Attachment, ConversationReference

# ============================================================================
# BOT CONFIGURATION
# ============================================================================

BOT_APP_ID = os.environ.get("BOT_APP_ID", "5e5ed2ce-14d5-46b8-93d5-0a473f3cd88c")
BOT_APP_PASSWORD = os.environ.get("BOT_APP_PASSWORD", "")
BOT_TENANT_ID = os.environ.get("BOT_TENANT_ID", "0591f50e-b7a3-41d0-a0b1-b26a2df48dfc")

SETTINGS = BotFrameworkAdapterSettings(
    app_id=BOT_APP_ID,
    app_password=BOT_APP_PASSWORD,
)
ADAPTER = BotFrameworkAdapter(SETTINGS)

# Conversation references for proactive messaging
CONVERSATION_REFERENCES = {}
CONV_REF_FILE = "conversation_references.json"


def load_conversation_references():
    """Load conversation references from file."""
    global CONVERSATION_REFERENCES
    if os.path.exists(CONV_REF_FILE):
        try:
            with open(CONV_REF_FILE, 'r') as f:
                CONVERSATION_REFERENCES = json.load(f)
            logger.info(f"Loaded {len(CONVERSATION_REFERENCES)} conversation references")
        except Exception as e:
            logger.error(f"Error loading conversation references: {e}")


def save_conversation_references():
    """Save conversation references to file."""
    try:
        with open(CONV_REF_FILE, 'w') as f:
            json.dump(CONVERSATION_REFERENCES, f)
    except Exception as e:
        logger.error(f"Error saving conversation references: {e}")


def add_conversation_reference(activity: Activity):
    """Store conversation reference for a user."""
    conv_ref = TurnContext.get_conversation_reference(activity)
    user_id = conv_ref.user.aad_object_id or conv_ref.user.id

    CONVERSATION_REFERENCES[user_id] = conv_ref.as_dict()
    save_conversation_references()

    logger.info(f"Stored conversation reference for user: {user_id}")
    return user_id


# ============================================================================
# BOT MESSAGE HANDLERS
# ============================================================================

async def on_message(turn_context: TurnContext):
    """Handle incoming messages."""
    user_id = add_conversation_reference(turn_context.activity)
    user_name = turn_context.activity.from_property.name or "there"

    text = turn_context.activity.text.lower() if turn_context.activity.text else ""

    if "help" in text:
        await turn_context.send_activity(
            "I'm Christina, your Call Notes assistant.\n\n"
            "I automatically send you summaries of your recruitment calls.\n\n"
            "Just keep this chat open - notes will appear here automatically!"
        )
    else:
        await turn_context.send_activity(
            f"Hi {user_name}! I'm Christina, your Call Notes assistant. "
            f"I'll send your automated call summaries here. "
            f"You're all set up!"
        )


async def on_members_added(turn_context: TurnContext):
    """Handle new members added to conversation."""
    for member in turn_context.activity.members_added:
        if member.id != turn_context.activity.recipient.id:
            add_conversation_reference(turn_context.activity)
            await turn_context.send_activity(
                "Welcome! I'm Christina, your Call Notes assistant. "
                "I'll automatically send you summaries of your recruitment calls here."
            )


async def on_turn(turn_context: TurnContext):
    """Main bot logic."""
    if turn_context.activity.type == ActivityTypes.message:
        await on_message(turn_context)
    elif turn_context.activity.type == ActivityTypes.conversation_update:
        await on_members_added(turn_context)
    elif turn_context.activity.type == ActivityTypes.install_update:
        add_conversation_reference(turn_context.activity)
        logger.info("App installed for user")


# ============================================================================
# PROACTIVE MESSAGING
# ============================================================================

async def send_proactive_card(user_aad_id: str, card: dict) -> bool:
    """Send an adaptive card to a user proactively."""
    if user_aad_id not in CONVERSATION_REFERENCES:
        logger.warning(f"No conversation reference for user: {user_aad_id}")
        return False

    conv_ref_dict = CONVERSATION_REFERENCES[user_aad_id]

    async def callback(turn_context: TurnContext):
        attachment = Attachment(
            content_type="application/vnd.microsoft.card.adaptive",
            content=card
        )
        activity = Activity(
            type=ActivityTypes.message,
            attachments=[attachment]
        )
        await turn_context.send_activity(activity)

    try:
        conv_ref = ConversationReference().from_dict(conv_ref_dict)
        await ADAPTER.continue_conversation(conv_ref, callback, BOT_APP_ID)
        logger.info(f"Sent proactive card to user: {user_aad_id}")
        return True
    except Exception as e:
        logger.error(f"Error sending proactive message: {e}")
        return False


# ============================================================================
# WEB ROUTES
# ============================================================================

async def messages(req: web.Request) -> web.Response:
    """Handle incoming bot messages from Teams."""
    if "application/json" in req.headers.get("Content-Type", ""):
        body = await req.json()
    else:
        return web.Response(status=415)

    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    try:
        response = await ADAPTER.process_activity(activity, auth_header, on_turn)
        if response:
            return web.json_response(data=response.body, status=response.status)
        return web.Response(status=201)
    except Exception as e:
        logger.error(f"Error processing activity: {e}")
        return web.Response(status=500, text=str(e))


async def api_send_note(req: web.Request) -> web.Response:
    """API endpoint to send a call note to a user."""
    try:
        data = await req.json()
        user_aad_id = data.get('user_aad_id')
        card = data.get('card')

        if not user_aad_id or not card:
            return web.json_response({"error": "user_aad_id and card required"}, status=400)

        success = await send_proactive_card(user_aad_id, card)

        if success:
            return web.json_response({"status": "sent"})
        else:
            return web.json_response({"error": "User not registered"}, status=404)

    except Exception as e:
        logger.error(f"Error in api_send_note: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def api_list_users(req: web.Request) -> web.Response:
    """List registered users."""
    return web.json_response({
        "users": list(CONVERSATION_REFERENCES.keys()),
        "count": len(CONVERSATION_REFERENCES)
    })


async def health(req: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({
        "status": "healthy",
        "bot_id": BOT_APP_ID,
        "registered_users": len(CONVERSATION_REFERENCES),
        "processor": "running"
    })


# ============================================================================
# PROCESSOR INTEGRATION
# ============================================================================

def run_processor_loop():
    """Run the PDF processor in a loop (background thread)."""
    POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', 60))

    logger.info(f"Starting processor loop (interval: {POLL_INTERVAL}s)")

    while True:
        try:
            processor.run_once()
        except Exception as e:
            logger.error(f"Error in processor: {e}")

        time.sleep(POLL_INTERVAL)


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point."""
    PORT = int(os.environ.get("PORT", 3978))

    logger.info("=" * 60)
    logger.info("Christina Call Notes - Starting")
    logger.info(f"Bot App ID: {BOT_APP_ID}")
    logger.info(f"Port: {PORT}")
    logger.info("=" * 60)

    # Load conversation references
    load_conversation_references()

    # Start processor in background thread
    processor_thread = threading.Thread(target=run_processor_loop, daemon=True)
    processor_thread.start()
    logger.info("Processor thread started")

    # Create and run web app
    app = web.Application()
    app.router.add_post("/api/messages", messages)
    app.router.add_post("/api/send-note", api_send_note)
    app.router.add_get("/api/users", api_list_users)
    app.router.add_get("/health", health)
    app.router.add_get("/", health)

    logger.info(f"Starting web server on port {PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
