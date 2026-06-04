"""Railway entry point. aiohttp web app + background poll thread.

Matches call-notes-bot's deployment shape: single process, $PORT, /health for
Railway's health check, plus a manual /poll trigger for testing/recovery.

Procfile: `web: python -m proforma_bot.server`
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

from aiohttp import web

from . import config, trigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
log = logging.getLogger("proforma_bot.server")

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))
_START_TIME = datetime.now(timezone.utc).isoformat()


async def health(_req: web.Request) -> web.Response:
    return web.json_response(
        {
            "status": "healthy",
            "mailbox": config.MERAKI1_MAILBOX,
            "sender_filter": config.CHRIS_PAINE_ADDRESS,
            "poll_interval_seconds": POLL_INTERVAL,
            "started_at": _START_TIME,
        }
    )


async def manual_poll(_req: web.Request) -> web.Response:
    """One-shot poll for testing. Runs synchronously so the response carries
    the summary — fine because we expect <25 messages per sweep."""
    try:
        counts = trigger.poll_once()
        return web.json_response({"status": "ok", **counts})
    except Exception as e:
        log.exception("manual /poll failed")
        return web.json_response({"status": "error", "error": str(e)}, status=500)


def _start_background_poller() -> None:
    t = threading.Thread(
        target=trigger.run_forever,
        args=(POLL_INTERVAL,),
        daemon=True,
        name="proforma-poller",
    )
    t.start()


def main() -> None:
    port = int(os.environ.get("PORT", "3979"))  # 3978 is call-notes-bot's port
    log.info("proforma_bot starting on port %d (poll every %ds)", port, POLL_INTERVAL)

    _start_background_poller()

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_post("/poll", manual_poll)
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
