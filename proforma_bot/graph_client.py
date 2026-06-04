"""Microsoft Graph access — ported from call-notes-bot's GraphAPIClient pattern.

Delegated auth as Joel via refresh token. Scopes here are MAIL-only because this
bot only reads the meraki1 shared mailbox. Christina keeps her own refresh token
for the Teams chat scopes — do not share token files between bots.

Env vars (same Entra ID app, different refresh token):
    MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, MS_REFRESH_TOKEN
"""
import logging
import os
import time
from typing import Any

import requests

from . import config

log = logging.getLogger("proforma_bot.graph")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = "Mail.Read.Shared Mail.ReadBasic.Shared Mail.Send.Shared User.Read offline_access"


class GraphAPIClient:
    """Token management ported from call-notes-bot/call_notes_processor.py:302.

    Refresh token loaded from env (preferred) or ms_refresh_token.txt (local dev).
    Rotation is persisted to file when running locally; on Railway the file is
    ephemeral, so the env var must be the source of truth — accepted limitation
    (refresh tokens last ~90 days, same as call-notes-bot)."""

    def __init__(self):
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_expires: float = 0
        self._load_refresh_token()

    def _load_refresh_token(self) -> None:
        if config.MS_REFRESH_TOKEN:
            self.refresh_token = config.MS_REFRESH_TOKEN
            return
        if os.path.exists("ms_refresh_token.txt"):
            with open("ms_refresh_token.txt") as f:
                self.refresh_token = f.read().strip()

    def _save_refresh_token(self) -> None:
        if self.refresh_token:
            with open("ms_refresh_token.txt", "w") as f:
                f.write(self.refresh_token)

    def _refresh_access_token(self) -> None:
        if not self.refresh_token:
            raise RuntimeError(
                "No refresh token. Run auth_setup.py once to seed MS_REFRESH_TOKEN."
            )

        url = f"https://login.microsoftonline.com/{config.MS_TENANT_ID}/oauth2/v2.0/token"
        data = {
            "client_id": config.MS_CLIENT_ID,
            "client_secret": config.MS_CLIENT_SECRET,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
            "scope": SCOPES,
        }
        r = requests.post(url, data=data, timeout=30)
        if r.status_code != 200:
            log.error("Token refresh failed: %s %s", r.status_code, r.text)
        r.raise_for_status()

        tokens = r.json()
        self.access_token = tokens["access_token"]
        self.token_expires = time.time() + tokens.get("expires_in", 3600) - 60
        if "refresh_token" in tokens:
            self.refresh_token = tokens["refresh_token"]
            self._save_refresh_token()
        log.info("Access token refreshed")

    def get_access_token(self) -> str:
        if not self.access_token or time.time() >= self.token_expires:
            self._refresh_access_token()
        return self.access_token  # type: ignore[return-value]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.get_access_token()}",
            "Content-Type": "application/json",
        }

    # ----- mail endpoints -----

    def get_message(self, message_id: str) -> dict[str, Any]:
        """Fetch a message from the meraki1 shared mailbox."""
        url = f"{GRAPH_BASE}/users/{config.MERAKI1_MAILBOX}/messages/{message_id}"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()

    def list_attachments(self, message_id: str) -> list[dict[str, Any]]:
        """Return attachments with name/size/contentType/isInline."""
        url = (
            f"{GRAPH_BASE}/users/{config.MERAKI1_MAILBOX}"
            f"/messages/{message_id}/attachments"
        )
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json().get("value", [])

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Return raw bytes for a fileAttachment. Uses $value for the binary blob."""
        url = (
            f"{GRAPH_BASE}/users/{config.MERAKI1_MAILBOX}"
            f"/messages/{message_id}/attachments/{attachment_id}/$value"
        )
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {self.get_access_token()}"},
            timeout=60,
        )
        r.raise_for_status()
        return r.content

    def list_unread_from(self, sender_address: str, top: int = 25) -> list[dict[str, Any]]:
        """Unread messages from a specific sender in the meraki1 inbox.

        Graph $filter caveat: 'from/emailAddress/address' is case-sensitive at
        the API layer, but Exchange normalises stored addresses to lowercase
        on receipt — so passing lowercase here is safe. Also filters hasAttachments
        eq true to skip plain replies, and orders oldest-first so we process in
        arrival order."""
        params = {
            "$filter": (
                f"isRead eq false and hasAttachments eq true "
                f"and from/emailAddress/address eq '{sender_address.lower()}'"
            ),
            "$select": "id,subject,receivedDateTime,from,hasAttachments",
            "$orderby": "receivedDateTime asc",
            "$top": str(top),
        }
        url = (
            f"{GRAPH_BASE}/users/{config.MERAKI1_MAILBOX}"
            f"/mailFolders/inbox/messages"
        )
        r = requests.get(url, headers=self._headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("value", [])

    def mark_as_read(self, message_id: str) -> None:
        url = f"{GRAPH_BASE}/users/{config.MERAKI1_MAILBOX}/messages/{message_id}"
        r = requests.patch(
            url, headers=self._headers(), json={"isRead": True}, timeout=30
        )
        r.raise_for_status()


# Module-level singleton — match call-notes-bot's usage pattern.
_client: GraphAPIClient | None = None


def _get_client() -> GraphAPIClient:
    global _client
    if _client is None:
        _client = GraphAPIClient()
    return _client


def get_message(message_id: str) -> dict[str, Any]:
    return _get_client().get_message(message_id)


def list_attachments(message_id: str) -> list[dict[str, Any]]:
    return _get_client().list_attachments(message_id)


def download_attachment(message_id: str, attachment_id: str) -> bytes:
    return _get_client().download_attachment(message_id, attachment_id)


def list_unread_from(sender_address: str, top: int = 25) -> list[dict[str, Any]]:
    return _get_client().list_unread_from(sender_address, top=top)


def mark_as_read(message_id: str) -> None:
    _get_client().mark_as_read(message_id)


def sender_address(message: dict[str, Any]) -> str:
    """Verified mailbox address only — NEVER trust display name (spec §4)."""
    return (
        message.get("from", {})
        .get("emailAddress", {})
        .get("address", "")
        .lower()
    )
