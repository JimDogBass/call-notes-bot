"""Inbox poller. Combines gmail_client + processed_store + orchestrator.

Dedup: two layers.
  1. Gmail IMAP \\Seen flag — set after a terminal outcome so the next
     UNSEEN search excludes it.
  2. processed_store.json — Message-ID set, checked BEFORE processing so we
     never reprocess if the \\Seen flag failed to apply between runs.

If the orchestrator raises, we leave the message unread AND don't write to
the processed store — the next poll picks it up. At Chris's volume (handful
per day) this is fine; if a poison message starts looping, mark it read in
Gmail manually.
"""
from __future__ import annotations

import logging
import time

from . import gmail_client, orchestrator, processed_store

log = logging.getLogger("proforma_bot.trigger")


def poll_once() -> dict[str, int]:
    counts = {"seen": 0, "processed": 0, "skipped": 0, "errors": 0}
    try:
        messages = gmail_client.check_inbox()
    except Exception as e:
        log.exception("check_inbox failed: %s", e)
        counts["errors"] += 1
        return counts

    counts["seen"] = len(messages)
    if not messages:
        return counts

    for msg in messages:
        if processed_store.is_processed(msg.message_id):
            log.info("already processed (Message-ID=%s); marking read", msg.message_id)
            try:
                gmail_client.mark_as_read(msg.uid)
            except Exception as e:
                log.error("mark_as_read failed for already-processed uid %s: %s", msg.uid, e)
            counts["skipped"] += 1
            continue

        try:
            result = orchestrator.handle(msg)
        except Exception as e:
            log.exception("handle failed for uid %s: %s", msg.uid, e)
            counts["errors"] += 1
            continue

        if result in orchestrator.TERMINAL_RESULTS:
            if result == orchestrator.RESULT_PROCESSED:
                processed_store.mark_processed(msg.message_id)
                counts["processed"] += 1
            else:
                counts["skipped"] += 1
            try:
                gmail_client.mark_as_read(msg.uid)
            except Exception as e:
                log.error("mark_as_read failed for uid %s: %s", msg.uid, e)
        else:
            log.warning("unknown result %r for uid %s; leaving unread", result, msg.uid)
            counts["errors"] += 1

    return counts


def run_forever(interval_seconds: int) -> None:
    log.info("starting poll loop (interval %ds)", interval_seconds)
    while True:
        try:
            counts = poll_once()
            if counts["seen"] or counts["errors"]:
                log.info("poll summary: %s", counts)
        except Exception as e:
            log.exception("poll_once raised at top level: %s", e)
        time.sleep(interval_seconds)
