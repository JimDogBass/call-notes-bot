"""Env-driven CONFIG values. Pattern borrowed from meraki-kpi-automation/config.py."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # only used in local dev

# --- Test flags (default safe) ---
TEST_MODE = os.environ.get("TEST_MODE", "true").lower() == "true"
TEST_RECIPIENT = os.environ.get("TEST_RECIPIENT", "joel.bentley@merakitalent.com")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# --- Gmail (IMAP + App Password) ---
GMAIL_USER = os.environ.get("GMAIL_USER", "merakitalent2@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
GMAIL_IMAP_SERVER = "imap.gmail.com"

# --- Microsoft Graph / Outlook (client credentials) ---
AZURE_TENANT_ID = os.environ.get("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET", "")
OUTLOOK_SENDER_EMAIL = os.environ.get("OUTLOOK_SENDER_EMAIL", "joel.bentley@merakitalent.com")
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# --- Trigger ---
CHRIS_PAINE_ADDRESS = os.environ.get("CHRIS_PAINE_ADDRESS", "chris.paine@merakitalent.com")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))

# --- Azure OpenAI (Fernando's resource) ---
AOAI_ENDPOINT = os.environ.get("AOAI_ENDPOINT", "")
AOAI_API_KEY = os.environ.get("AOAI_API_KEY", "")
AOAI_DEPLOYMENT = os.environ.get("AOAI_DEPLOYMENT", "gpt-4o-mini")
AOAI_API_VERSION = os.environ.get("AOAI_API_VERSION", "2024-08-01-preview")

# --- Template (package-relative default so it works regardless of cwd) ---
TEMPLATE_PATH = os.environ.get(
    "TEMPLATE_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "templates", "pwc_proforma_template.docx",
    ),
)
