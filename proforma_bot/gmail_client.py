"""Gmail IMAP monitor — ported from meraki-kpi-automation/gmail_monitor.py.

Filter: UNSEEN messages from CHRIS_PAINE_ADDRESS that have a CV-shaped
attachment (docx/pdf, not the tiny inline sig images forwards drag along).
"""
from __future__ import annotations

import email
import email.message
import imaplib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime

from . import config

log = logging.getLogger("proforma_bot.gmail")

_MIN_ATTACHMENT_BYTES = 10_000  # skip inline signature images


@dataclass
class IncomingEmail:
    uid: bytes
    subject: str
    sender: str
    received_date: datetime
    message_id: str  # RFC 822 Message-ID for dedup
    body_text: str
    body_html: str
    cv_filename: str = field(repr=False)
    cv_bytes: bytes = field(repr=False)


def _connect() -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(config.GMAIL_IMAP_SERVER)
    conn.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
    return conn


def _parse_date(date_str: str) -> datetime:
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now()


def _extract_bodies(msg: email.message.Message) -> tuple[str, str]:
    """Return (plain_text, html). Either may be empty."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = payload.decode("utf-8", errors="replace")
        if ctype == "text/plain":
            plain_parts.append(text)
        elif ctype == "text/html":
            html_parts.append(text)
    return "\n".join(plain_parts), "\n".join(html_parts)


def _pick_cv_attachment(msg: email.message.Message) -> tuple[str, bytes] | None:
    """Walk MIME parts. Prefer filename containing 'cv'; else largest doc/pdf
    above the inline-image threshold."""
    candidates: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename() or ""
        lower = filename.lower()
        if not lower.endswith((".docx", ".pdf", ".doc")):
            continue
        payload = part.get_payload(decode=True)
        if not payload or len(payload) < _MIN_ATTACHMENT_BYTES:
            continue
        candidates.append((filename, payload))

    if not candidates:
        return None
    cv_named = [c for c in candidates if "cv" in c[0].lower()]
    pool = cv_named or candidates
    return max(pool, key=lambda c: len(c[1]))


def _sender_address(msg: email.message.Message) -> str:
    """Extract bare address from 'Name <addr@domain>' or just 'addr@domain'."""
    from email.utils import parseaddr
    _, addr = parseaddr(msg.get("From", ""))
    return addr.lower().strip()


def check_inbox() -> list[IncomingEmail]:
    """Unread emails from Chris with a usable CV attachment.

    Does NOT mark anything read — caller invokes mark_as_read() after the
    pipeline succeeds. processed_store provides belt-and-braces idempotency
    in case marking fails between runs.
    """
    chris = config.CHRIS_PAINE_ADDRESS.lower()
    results: list[IncomingEmail] = []
    conn = _connect()
    try:
        conn.select("INBOX")
        # IMAP supports a FROM filter; combined with UNSEEN this is cheap.
        _, data = conn.search(None, "UNSEEN", "FROM", chris)
        uids = data[0].split()
        if not uids:
            return results

        log.info("found %d unread from %s", len(uids), chris)
        for uid in uids:
            _, msg_data = conn.fetch(uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            sender = _sender_address(msg)
            if sender != chris:
                # IMAP FROM is fuzzy; verify the parsed bare address matches.
                log.info("uid %s: sender %s != %s; skip", uid, sender, chris)
                continue

            picked = _pick_cv_attachment(msg)
            if picked is None:
                log.info("uid %s: no usable CV attachment; skip", uid)
                continue

            plain, html = _extract_bodies(msg)
            results.append(
                IncomingEmail(
                    uid=uid,
                    subject=msg.get("Subject", "").strip(),
                    sender=sender,
                    received_date=_parse_date(msg.get("Date", "")),
                    message_id=msg.get("Message-ID", "").strip(),
                    body_text=plain,
                    body_html=html,
                    cv_filename=picked[0],
                    cv_bytes=picked[1],
                )
            )
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return results


def mark_as_read(uid: bytes) -> None:
    conn = _connect()
    try:
        conn.select("INBOX")
        conn.store(uid, "+FLAGS", "\\Seen")
    finally:
        try:
            conn.logout()
        except Exception:
            pass
