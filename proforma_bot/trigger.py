"""Inbox poller.

Why polling instead of a Graph change-notification subscription:
  - Subscriptions for mail expire every ~3 days; we'd need a renewal job, a
    public HTTPS endpoint with validation handshake, and lifecycle webhooks.
  - Chris forwards at low volume (handful/day at most). Sub-minute latency isn't
    a product requirement. A 60s poll is dramatically simpler and stateless.

Dedup strategy: mark-as-read after a terminal outcome (processed or "no usable
attachment"). The $filter is "isRead eq false AND from == Chris AND
hasAttachments eq true" — so once we mark a message read, it falls out of the
result set on the next poll. State lives in the mailbox itself; no Railway-
volume or sheet needed.

Failure handling: if handle_message raises (LLM error, Graph 5xx, render
failure), we LEAVE the message unread and log. Operator marks it manually
after investigating; we never silently retry-forever a poison message because
the next poll picks it up too, which is OK at this volume. If retries become
noisy, add a max-attempt category tag.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from . import config, graph_client, main as orchestrator

log = logging.getLogger("proforma_bot.trigger")


def poll_once() -> dict[str, int]:
    """One sweep of the meraki1 inbox. Returns a counts summary for logging."""
    if not config.CHRIS_PAINE_ADDRESS:
        log.warning("CHRIS_PAINE_ADDRESS not set; poll skipped")
        return {"skipped": 1}

    messages = graph_client.list_unread_from(config.CHRIS_PAINE_ADDRESS)
    counts = {"seen": len(messages), "processed": 0, "ignored": 0, "errors": 0}
    if not messages:
        return counts

    log.info("poll: %d unread from Chris", len(messages))
    for msg in messages:
        mid = msg["id"]
        try:
            result = orchestrator.handle_message(mid)
        except Exception as e:
            log.exception("handle_message failed for %s: %s", mid, e)
            counts["errors"] += 1
            continue

        if result in orchestrator.TERMINAL_RESULTS:
            try:
                graph_client.mark_as_read(mid)
            except Exception as e:
                log.error("mark_as_read failed for %s: %s", mid, e)
            if result == orchestrator.RESULT_PROCESSED:
                counts["processed"] += 1
            else:
                counts["ignored"] += 1
        else:
            log.warning("unknown result %r for %s; leaving unread", result, mid)
            counts["errors"] += 1

    return counts


def run_forever(interval_seconds: int) -> None:
    """Long-running poll loop. Caller is expected to run this in a daemon thread."""
    log.info("starting poll loop (interval %ds)", interval_seconds)
    while True:
        try:
            counts = poll_once()
            if counts.get("seen"):
                log.info("poll summary: %s", counts)
        except Exception as e:
            # Defensive: never let the loop die. Individual-message errors are
            # already caught above; this catches list-call/auth-refresh failures.
            log.exception("poll_once raised: %s", e)
        time.sleep(interval_seconds)
