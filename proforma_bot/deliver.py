"""Email the finished proforma to Chris from Joel's Outlook via Graph.

Sender is OUTLOOK_SENDER_EMAIL (Joel), not meraki1@gmail — Chris expects the
submittal to look like it came from his recruitment counterpart, and Joel's
Outlook mailbox is the credentialed identity the Entra app is permitted to
send as."""
from __future__ import annotations

import logging
import os

from . import config
from .outlook_sender import get_sender

log = logging.getLogger("proforma_bot.deliver")


def deliver(
    docx_path: str,
    candidate_name: str = "",
    body_text: str | None = None,
) -> None:
    with open(docx_path, "rb") as f:
        docx_bytes = f.read()

    subject = (
        f"PwC CV Submittal – {candidate_name}"
        if candidate_name
        else "PwC CV Submittal"
    )
    if body_text is None:
        body_text = (
            "Proforma attached. Highlighted fields need your review/confirmation "
            "before forwarding to PwC."
        )

    get_sender().send(
        to=config.CHRIS_PAINE_ADDRESS,
        subject=subject,
        body_text=body_text,
        attachment_bytes=docx_bytes,
        attachment_name=os.path.basename(docx_path),
    )
