"""
Christina Call Notes - Combined Bot Server + Processor
Runs the bot web server and the PDF processor in the same process.
"""

import os
import asyncio
import threading
import time
import logging
from datetime import datetime

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

# Google Sheets for persistent storage
from google.oauth2 import service_account
from googleapiclient.discovery import build
import base64

# ============================================================================
# BOT CONFIGURATION
# ============================================================================

BOT_APP_ID = os.environ.get("BOT_APP_ID", "5e5ed2ce-14d5-46b8-93d5-0a473f3cd88c")
BOT_APP_PASSWORD = os.environ.get("BOT_APP_PASSWORD", "")
BOT_TENANT_ID = os.environ.get("BOT_TENANT_ID", "0591f50e-b7a3-41d0-a0b1-b26a2df48dfc")

SETTINGS = BotFrameworkAdapterSettings(
    app_id=BOT_APP_ID,
    app_password=BOT_APP_PASSWORD,
    channel_auth_tenant=BOT_TENANT_ID,  # Required for single tenant bots
)
ADAPTER = BotFrameworkAdapter(SETTINGS)

# Conversation references for proactive messaging
CONVERSATION_REFERENCES = {}

# Google Sheets configuration (same as processor)
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "meraki-n8n-automation-66a9d5aafc1e.json")
GOOGLE_SPREADSHEET_ID = os.environ.get("GOOGLE_SPREADSHEET_ID", "1Z_5rhbhe4lW13t4DKOzhWW-cKLbeyneUHTZXBUmBM-g")

# Sheets service (initialized on first use)
_sheets_service = None


def get_sheets_service():
    """Get Google Sheets service (singleton)."""
    global _sheets_service
    if _sheets_service is None:
        scopes = ['https://www.googleapis.com/auth/spreadsheets']

        if GOOGLE_SERVICE_ACCOUNT_JSON:
            json_str = GOOGLE_SERVICE_ACCOUNT_JSON
            try:
                json_str = base64.b64decode(json_str).decode('utf-8')
            except Exception:
                pass
            service_account_info = json.loads(json_str)
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info, scopes=scopes
            )
        else:
            credentials = service_account.Credentials.from_service_account_file(
                GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes
            )

        _sheets_service = build('sheets', 'v4', credentials=credentials)
    return _sheets_service


def load_conversation_references():
    """Load conversation references from Google Sheets."""
    global CONVERSATION_REFERENCES
    try:
        sheets = get_sheets_service()
        result = sheets.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SPREADSHEET_ID,
            range='ConversationReferences!A:C'
        ).execute()
        rows = result.get('values', [])

        if len(rows) > 1:  # Skip header row
            for row in rows[1:]:
                if len(row) >= 2:
                    user_id = row[0]
                    conv_ref_json = row[1]
                    try:
                        CONVERSATION_REFERENCES[user_id] = json.loads(conv_ref_json)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON for user {user_id}")

        logger.info(f"Loaded {len(CONVERSATION_REFERENCES)} conversation references from Google Sheets")
    except Exception as e:
        # If sheet doesn't exist yet, that's okay
        if "Unable to parse range" in str(e) or "not found" in str(e).lower():
            logger.info("ConversationReferences sheet not found - will be created on first registration")
        else:
            logger.error(f"Error loading conversation references: {e}")


def save_conversation_reference(user_id: str, conv_ref: dict):
    """Save a single conversation reference to Google Sheets."""
    try:
        sheets = get_sheets_service()

        # First, try to find if user already exists
        try:
            result = sheets.spreadsheets().values().get(
                spreadsheetId=GOOGLE_SPREADSHEET_ID,
                range='ConversationReferences!A:A'
            ).execute()
            rows = result.get('values', [])

            # Find row index for this user (1-indexed, +1 for header)
            row_index = None
            for i, row in enumerate(rows):
                if row and row[0] == user_id:
                    row_index = i + 1  # 1-indexed
                    break

            timestamp = datetime.now().isoformat()
            conv_ref_json = json.dumps(conv_ref)

            if row_index:
                # Update existing row
                sheets.spreadsheets().values().update(
                    spreadsheetId=GOOGLE_SPREADSHEET_ID,
                    range=f'ConversationReferences!A{row_index}:C{row_index}',
                    valueInputOption='RAW',
                    body={'values': [[user_id, conv_ref_json, timestamp]]}
                ).execute()
                logger.info(f"Updated conversation reference for user: {user_id}")
            else:
                # Append new row
                sheets.spreadsheets().values().append(
                    spreadsheetId=GOOGLE_SPREADSHEET_ID,
                    range='ConversationReferences!A:C',
                    valueInputOption='RAW',
                    body={'values': [[user_id, conv_ref_json, timestamp]]}
                ).execute()
                logger.info(f"Added new conversation reference for user: {user_id}")

        except Exception as e:
            if "Unable to parse range" in str(e) or "not found" in str(e).lower():
                # Sheet doesn't exist, create it with header and first row
                sheets.spreadsheets().values().append(
                    spreadsheetId=GOOGLE_SPREADSHEET_ID,
                    range='ConversationReferences!A:C',
                    valueInputOption='RAW',
                    body={'values': [
                        ['UserAADId', 'ConversationReferenceJSON', 'UpdatedAt'],
                        [user_id, json.dumps(conv_ref), datetime.now().isoformat()]
                    ]}
                ).execute()
                logger.info(f"Created ConversationReferences sheet and added user: {user_id}")
            else:
                raise

    except Exception as e:
        logger.error(f"Error saving conversation reference: {e}")


def add_conversation_reference(activity: Activity):
    """Store conversation reference for a user."""
    conv_ref = TurnContext.get_conversation_reference(activity)
    user_id = conv_ref.user.aad_object_id or conv_ref.user.id

    conv_ref_dict = conv_ref.as_dict()
    CONVERSATION_REFERENCES[user_id] = conv_ref_dict

    # Save to Google Sheets (persistent storage)
    save_conversation_reference(user_id, conv_ref_dict)

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

async def send_proactive_card(user_aad_id: str, card: dict) -> tuple:
    """Send an adaptive card to a user proactively. Returns (success, error_message)."""
    if user_aad_id not in CONVERSATION_REFERENCES:
        logger.warning(f"No conversation reference for user: {user_aad_id}")
        return False, "User not registered"

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
        return True, None
    except Exception as e:
        logger.error(f"Error sending proactive message: {e}")
        return False, str(e)


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

        success, error = await send_proactive_card(user_aad_id, card)

        if success:
            return web.json_response({"status": "sent"})
        else:
            return web.json_response({"error": error}, status=404)

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
