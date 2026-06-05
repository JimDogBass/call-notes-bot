"""Send email via Microsoft Graph using MSAL client credentials.
Ported from meraki-kpi-automation/outlook_sender.py; generalised to accept a
named file attachment (the rendered .docx) instead of a CSV."""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone

import requests
from msal import ConfidentialClientApplication

from . import config

log = logging.getLogger("proforma_bot.outlook")


class OutlookSender:
    def __init__(self):
        self.app = ConfidentialClientApplication(
            client_id=config.AZURE_CLIENT_ID,
            client_credential=config.AZURE_CLIENT_SECRET,
            authority=f"https://login.microsoftonline.com/{config.AZURE_TENANT_ID}",
        )
        self._token: str | None = None
        self._token_expiry: datetime | None = None

    def _get_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._token and self._token_expiry and now < self._token_expiry:
            return self._token

        result = self.app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise RuntimeError(
                f"Failed to acquire Graph token: {result.get('error_description', result)}"
            )
        self._token = result["access_token"]
        # Re-use for ~50 minutes (token TTL is usually 60).
        self._token_expiry = now + timedelta(minutes=50)
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def send(
        self,
        to: str,
        subject: str,
        body_text: str,
        attachments: list[dict] | None = None,
    ) -> None:
        """Send a message via Graph. `attachments` is a list of
        {"name": str, "bytes": bytes, "content_type": str} dicts; order is
        preserved in the outgoing message."""
        original_to = to
        if config.DRY_RUN:
            log.info("DRY_RUN: would send %r -> %s (skipped)", subject, to)
            return

        if config.TEST_MODE:
            subject = f"[TO: {original_to}] {subject}"
            to = config.TEST_RECIPIENT
            log.info("TEST_MODE: redirecting %s -> %s", original_to, to)

        message: dict = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body_text},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        }
        if attachments:
            message["message"]["attachments"] = [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": a["name"],
                    "contentType": a["content_type"],
                    "contentBytes": base64.b64encode(a["bytes"]).decode("ascii"),
                }
                for a in attachments
            ]

        url = f"{config.GRAPH_BASE_URL}/users/{config.OUTLOOK_SENDER_EMAIL}/sendMail"
        r = requests.post(url, json=message, headers=self._headers(), timeout=60)
        if r.status_code not in (200, 202):
            log.error("sendMail failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
        log.info(
            "sent %r -> %s (attachments=%d)", subject, to, len(attachments or [])
        )


_singleton: OutlookSender | None = None


def get_sender() -> OutlookSender:
    global _singleton
    if _singleton is None:
        _singleton = OutlookSender()
    return _singleton
