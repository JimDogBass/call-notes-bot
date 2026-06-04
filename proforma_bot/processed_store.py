"""Idempotency cache of processed Message-IDs.
Ported from meraki-kpi-automation/processed_store.py.

Belt-and-braces against IMAP \\Seen flag failing to apply between processing
and the next poll. Stored as a JSON list; point PROCESSED_STORE_PATH at a
Railway volume to persist across deploys."""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("proforma_bot.store")

STORE_PATH = os.environ.get(
    "PROCESSED_STORE_PATH",
    os.path.join(os.path.dirname(__file__), "processed_emails.json"),
)
MAX_ENTRIES = 500


def _load() -> list[str]:
    if not os.path.exists(STORE_PATH):
        return []
    try:
        with open(STORE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("processed-store load failed: %s", e)
        return []


def _save(data: list[str]) -> None:
    with open(STORE_PATH, "w") as f:
        json.dump(data, f, indent=2)


def is_processed(message_id: str) -> bool:
    if not message_id:
        return False
    return message_id in _load()


def mark_processed(message_id: str) -> None:
    if not message_id:
        return
    entries = _load()
    if message_id not in entries:
        entries.append(message_id)
        if len(entries) > MAX_ENTRIES:
            entries = entries[-MAX_ENTRIES:]
        _save(entries)
