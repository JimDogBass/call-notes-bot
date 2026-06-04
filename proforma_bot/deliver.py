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


def deliver(docx_path: str, candidate_name: str = "") -> None:
    with open(docx_path, "rb") as f:
        docx_bytes = f.read()

    subject = (
        f"PwC Proforma — {candidate_name}" if candidate_name else "PwC Proforma"
    )
    body = (
        f"Proforma attached for {candidate_name}.\n\n"
        "Rate (Inc. Charge) is left as [TBC] — fill in the real charge rate before sending on."
        if candidate_name
        else "Proforma attached. Rate (Inc. Charge) is left as [TBC]."
    )

    get_sender().send(
        to=config.CHRIS_PAINE_ADDRESS,
        subject=subject,
        body_text=body,
        attachment_bytes=docx_bytes,
        attachment_name=os.path.basename(docx_path),
    )
