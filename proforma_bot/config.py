"""Env-driven CONFIG values. Match the call-notes-bot pattern."""
import os

# Mailbox + delivery target
MERAKI1_MAILBOX = os.environ.get("MERAKI1_MAILBOX", "")
CHRIS_PAINE_ADDRESS = os.environ.get("CHRIS_PAINE_ADDRESS", "")

# Microsoft Graph (same Entra ID app as call-notes-bot; proforma_bot needs its
# OWN refresh token because the scopes differ — Mail.Read.Shared vs Chat.*).
MS_TENANT_ID = os.environ.get("MS_TENANT_ID", "")
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET", "")
MS_REFRESH_TOKEN = os.environ.get("MS_REFRESH_TOKEN", "")

# Azure OpenAI
AOAI_ENDPOINT = os.environ.get("AOAI_ENDPOINT", "")
AOAI_API_KEY = os.environ.get("AOAI_API_KEY", "")
AOAI_DEPLOYMENT = os.environ.get("AOAI_DEPLOYMENT", "gpt-4o-mini")
AOAI_API_VERSION = os.environ.get("AOAI_API_VERSION", "2024-08-01-preview")

TEMPLATE_PATH = os.environ.get(
    "TEMPLATE_PATH", "templates/pwc_proforma_template.docx"
)

# TODO: import Christina's send-file-to-person function path here once confirmed
# e.g. CHRISTINA_SEND_FN = "call_notes_bot.deliver.send_file_to_user"
