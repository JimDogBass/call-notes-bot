"""Email the finished proforma + original CV to Chris from Joel's Outlook via Graph.

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


_CONTENT_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
}


def _content_type_for(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def deliver(
    docx_path: str,
    cv_filename: str,
    cv_bytes: bytes,
    candidate_name: str = "",
    role: str = "",
    body_text: str | None = None,
) -> None:
    with open(docx_path, "rb") as f:
        docx_bytes = f.read()

    # Subject builds up as "PwC CV Submittal – {candidate} – {role}", skipping
    # whichever pieces are empty so the dash separators don't show as gaps.
    subject_parts = ["PwC CV Submittal"]
    if candidate_name:
        subject_parts.append(candidate_name)
    if role:
        subject_parts.append(role)
    subject = " – ".join(subject_parts)

    if body_text is None:
        body_text = (
            "Proforma attached. Highlighted fields need your review/confirmation "
            "before forwarding to PwC."
        )

    attachments = [
        {
            "name": os.path.basename(docx_path),
            "bytes": docx_bytes,
            "content_type": _CONTENT_TYPES[".docx"],
        },
        {
            "name": cv_filename,
            "bytes": cv_bytes,
            "content_type": _content_type_for(cv_filename),
        },
    ]

    get_sender().send(
        to=config.CHRIS_PAINE_ADDRESS,
        subject=subject,
        body_text=body_text,
        attachments=attachments,
    )
