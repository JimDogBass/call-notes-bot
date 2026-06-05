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

# Switch from inline sendMail (cap ~4 MB request) to draft + upload-session
# when total raw attachment bytes exceed this. 2.5 MB raw ≈ 3.3 MB after
# base64 inflation, leaving headroom under Graph's documented inline ceiling.
LARGE_ATTACHMENT_THRESHOLD = 2_500_000

# Per-attachment inline POST limit on a draft message. Above this we must use
# createUploadSession for that specific attachment.
INLINE_ATTACHMENT_LIMIT = 3 * 1024 * 1024

# Graph requires upload-session chunks to be a multiple of 320 KiB (327680B)
# except for the final chunk. 10 × 320 KiB = 3.125 MB is a comfortable size
# that fits well under per-request limits.
UPLOAD_CHUNK_SIZE = 3_276_800


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
        cc: list[str] | None = None,
    ) -> None:
        """Send a message via Graph. `attachments` is a list of
        {"name": str, "bytes": bytes, "content_type": str} dicts; order is
        preserved in the outgoing message.

        Routes through inline sendMail when total attachment bytes fit
        comfortably under Graph's per-request ceiling, otherwise creates a
        draft, attaches each item (upload-session for any over
        INLINE_ATTACHMENT_LIMIT), and posts /send."""
        original_to = to
        if config.DRY_RUN:
            log.info("DRY_RUN: would send %r -> %s (skipped)", subject, to)
            return

        if config.TEST_MODE:
            subject = f"[TO: {original_to}] {subject}"
            to = config.TEST_RECIPIENT
            cc = None
            log.info("TEST_MODE: redirecting %s -> %s", original_to, to)

        total = sum(len(a["bytes"]) for a in (attachments or []))
        if total > LARGE_ATTACHMENT_THRESHOLD:
            self._send_via_draft(to, cc, subject, body_text, attachments or [])
        else:
            self._send_inline(to, cc, subject, body_text, attachments)

    def _send_inline(
        self,
        to: str,
        cc: list[str] | None,
        subject: str,
        body_text: str,
        attachments: list[dict] | None,
    ) -> None:
        message: dict = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body_text},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        }
        if cc:
            message["message"]["ccRecipients"] = [
                {"emailAddress": {"address": addr}} for addr in cc
            ]
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
            "sent %r -> %s (inline, attachments=%d)",
            subject, to, len(attachments or []),
        )

    def _send_via_draft(
        self,
        to: str,
        cc: list[str] | None,
        subject: str,
        body_text: str,
        attachments: list[dict],
    ) -> None:
        base = f"{config.GRAPH_BASE_URL}/users/{config.OUTLOOK_SENDER_EMAIL}"
        draft: dict = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body_text},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
        if cc:
            draft["ccRecipients"] = [
                {"emailAddress": {"address": addr}} for addr in cc
            ]
        r = requests.post(
            f"{base}/messages", json=draft, headers=self._headers(), timeout=60,
        )
        if r.status_code not in (200, 201):
            log.error("draft create failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
        message_id = r.json()["id"]

        for a in attachments:
            if len(a["bytes"]) <= INLINE_ATTACHMENT_LIMIT:
                self._attach_inline(message_id, a)
            else:
                self._attach_upload_session(message_id, a)

        send_r = requests.post(
            f"{base}/messages/{message_id}/send",
            headers=self._headers(),
            timeout=60,
        )
        if send_r.status_code not in (200, 202):
            log.error("draft send failed: %s %s", send_r.status_code, send_r.text)
        send_r.raise_for_status()
        log.info(
            "sent %r -> %s (draft, attachments=%d, total_bytes=%d)",
            subject, to, len(attachments),
            sum(len(a["bytes"]) for a in attachments),
        )

    def _attach_inline(self, message_id: str, attachment: dict) -> None:
        base = f"{config.GRAPH_BASE_URL}/users/{config.OUTLOOK_SENDER_EMAIL}"
        body = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": attachment["name"],
            "contentType": attachment["content_type"],
            "contentBytes": base64.b64encode(attachment["bytes"]).decode("ascii"),
        }
        r = requests.post(
            f"{base}/messages/{message_id}/attachments",
            json=body,
            headers=self._headers(),
            timeout=60,
        )
        if r.status_code not in (200, 201):
            log.error("inline attach failed: %s %s", r.status_code, r.text)
        r.raise_for_status()

    def _attach_upload_session(self, message_id: str, attachment: dict) -> None:
        base = f"{config.GRAPH_BASE_URL}/users/{config.OUTLOOK_SENDER_EMAIL}"
        total_size = len(attachment["bytes"])
        create_body = {
            "AttachmentItem": {
                "attachmentType": "file",
                "name": attachment["name"],
                "size": total_size,
                "contentType": attachment["content_type"],
            }
        }
        r = requests.post(
            f"{base}/messages/{message_id}/attachments/createUploadSession",
            json=create_body,
            headers=self._headers(),
            timeout=60,
        )
        if r.status_code not in (200, 201):
            log.error("createUploadSession failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
        upload_url = r.json()["uploadUrl"]

        data = attachment["bytes"]
        offset = 0
        while offset < total_size:
            end = min(offset + UPLOAD_CHUNK_SIZE, total_size)
            chunk = data[offset:end]
            # Pre-authenticated URL — do NOT send the bearer header here.
            put = requests.put(
                upload_url,
                data=chunk,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end - 1}/{total_size}",
                },
                timeout=120,
            )
            if put.status_code not in (200, 201, 202):
                log.error(
                    "upload chunk failed @%d-%d: %s %s",
                    offset, end - 1, put.status_code, put.text,
                )
            put.raise_for_status()
            offset = end


_singleton: OutlookSender | None = None


def get_sender() -> OutlookSender:
    global _singleton
    if _singleton is None:
        _singleton = OutlookSender()
    return _singleton
