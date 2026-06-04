"""Email the finished proforma from meraki1 to Chris Paine via Graph sendMail.

Architecture deviation from spec §2: Christina has no file-delivery path
(she only sends adaptive cards), so we skip Teams and email the .docx instead.
Reuses the Graph auth already wired for inbox reads — just needs Mail.Send.Shared
added to the refresh token's scopes."""
import base64
import logging
import os
from typing import Any

import requests

from . import config
from .graph_client import GRAPH_BASE, _get_client

log = logging.getLogger("proforma_bot.deliver")


def _build_message(docx_path: str, candidate_name: str = "") -> dict[str, Any]:
    with open(docx_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("ascii")

    filename = os.path.basename(docx_path)
    subject = (
        f"PwC Proforma — {candidate_name}" if candidate_name else "PwC Proforma"
    )
    body = (
        f"Proforma attached for {candidate_name}.\n\n"
        "Rate (Inc. Charge) is left as [TBC] — fill in the real charge rate before sending on."
        if candidate_name
        else "Proforma attached. Rate (Inc. Charge) is left as [TBC]."
    )

    return {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [
                {"emailAddress": {"address": config.CHRIS_PAINE_ADDRESS}}
            ],
            "attachments": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": filename,
                    "contentType": (
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document"
                    ),
                    "contentBytes": content_b64,
                }
            ],
        },
        "saveToSentItems": True,
    }


def deliver(docx_path: str, candidate_name: str = "") -> None:
    """Send the .docx from meraki1 to Chris. Filename is preserved verbatim."""
    client = _get_client()
    url = f"{GRAPH_BASE}/users/{config.MERAKI1_MAILBOX}/sendMail"
    payload = _build_message(docx_path, candidate_name)

    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {client.get_access_token()}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    if r.status_code not in (200, 202):
        log.error("sendMail failed: %s %s", r.status_code, r.text)
    r.raise_for_status()
    log.info("Proforma emailed to %s", config.CHRIS_PAINE_ADDRESS)
