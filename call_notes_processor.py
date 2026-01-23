"""
Meraki Call Notes Processor
Extracts candidate information from call transcripts and sends to consultants via Teams.

Author: Joel @ Meraki Talent
Date: January 2026
"""

import os
import re
import json
import time
import logging
import base64
from datetime import datetime
from typing import Optional, Dict, Any

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import pdfplumber
import PyPDF2
import io

# ============================================================================
# CONFIGURATION (from environment variables, with fallback to defaults)
# ============================================================================

# Google
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "meraki-n8n-automation-66a9d5aafc1e.json")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")  # For Railway: paste full JSON
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "1SfFPHC1DRUzcR8FDcdQkzr5oJZhtNSzr")
GOOGLE_SPREADSHEET_ID = os.environ.get("GOOGLE_SPREADSHEET_ID", "1Z_5rhbhe4lW13t4DKOzhWW-cKLbeyneUHTZXBUmBM-g")

# Azure OpenAI
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

# Microsoft Graph (Delegated OAuth2)
MS_TENANT_ID = os.environ.get("MS_TENANT_ID", "")
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET", "")
MS_REFRESH_TOKEN = os.environ.get("MS_REFRESH_TOKEN", "")
JOEL_AAD_ID = os.environ.get("JOEL_AAD_ID", "")

# Processing
WORD_COUNT_THRESHOLD = int(os.environ.get("WORD_COUNT_THRESHOLD", "300"))
PROCESSED_PREFIX = "[PROCESSED] "

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# GOOGLE SERVICES
# ============================================================================

def get_google_services():
    """Initialize Google Drive and Sheets services."""
    scopes = [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/spreadsheets'
    ]

    # Use JSON from environment variable (Railway) or file (local)
    if GOOGLE_SERVICE_ACCOUNT_JSON:
        json_str = GOOGLE_SERVICE_ACCOUNT_JSON

        # Try base64 decode first (for Railway)
        try:
            json_str = base64.b64decode(json_str).decode('utf-8')
            logger.info("Decoded base64 service account JSON")
        except Exception:
            # Not base64, use as-is
            pass

        service_account_info = json.loads(json_str)
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=scopes
        )
    else:
        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_FILE,
            scopes=scopes
        )

    drive_service = build('drive', 'v3', credentials=credentials)
    sheets_service = build('sheets', 'v4', credentials=credentials)
    return drive_service, sheets_service


def get_new_pdf_files(drive_service) -> list:
    """Get unprocessed PDF files from Google Drive folder."""
    query = f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and mimeType='application/pdf' and not name contains '{PROCESSED_PREFIX}'"
    results = drive_service.files().list(
        q=query,
        fields="files(id, name, createdTime)",
        orderBy="createdTime desc"
    ).execute()
    return results.get('files', [])


def download_pdf(drive_service, file_id: str) -> bytes:
    """Download PDF file content from Google Drive."""
    request = drive_service.files().get_media(fileId=file_id)
    file_content = io.BytesIO()
    downloader = MediaIoBaseDownload(file_content, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    file_content.seek(0)
    return file_content.read()


def rename_processed_file(drive_service, file_id: str, original_name: str):
    """Rename file to mark as processed."""
    new_name = f"{PROCESSED_PREFIX}{original_name}"
    drive_service.files().update(
        fileId=file_id,
        body={'name': new_name}
    ).execute()
    logger.info(f"Renamed file to: {new_name}")


def get_consultants(sheets_service) -> Dict[str, Dict]:
    """Load consultants from Google Sheets."""
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=GOOGLE_SPREADSHEET_ID,
        range='Consultants!A:E'
    ).execute()
    rows = result.get('values', [])

    if not rows:
        return {}

    headers = rows[0]
    consultants = {}

    for row in rows[1:]:
        if len(row) >= 5:
            name = row[0].strip()
            consultants[name.lower()] = {
                'Name': name,
                'Email': row[1] if len(row) > 1 else '',
                'Desk': row[2] if len(row) > 2 else '',
                'TeamsUserId': row[3] if len(row) > 3 else '',
                'Active': row[4].upper() == 'TRUE' if len(row) > 4 else False
            }

    return consultants


def get_prompts(sheets_service) -> Dict[str, str]:
    """Load desk prompts from Google Sheets."""
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=GOOGLE_SPREADSHEET_ID,
        range='Prompts!A:B'
    ).execute()
    rows = result.get('values', [])

    if not rows:
        return {}

    prompts = {}
    for row in rows[1:]:  # Skip header
        if len(row) >= 2:
            desk = row[0].strip()
            prompt = row[1]
            prompts[desk] = prompt

    return prompts


def log_skipped_call(sheets_service, filename: str, word_count: int, reason: str, consultant_name: str = ''):
    """Log skipped call to Google Sheets."""
    values = [[
        filename,
        datetime.now().isoformat(),
        word_count,
        reason,
        consultant_name
    ]]
    sheets_service.spreadsheets().values().append(
        spreadsheetId=GOOGLE_SPREADSHEET_ID,
        range='Skipped_Calls!A:E',
        valueInputOption='RAW',
        body={'values': values}
    ).execute()
    logger.info(f"Logged skipped call: {filename} - {reason}")


def log_processing_error(sheets_service, filename: str, error_message: str, node_name: str):
    """Log processing error to Google Sheets."""
    values = [[
        filename,
        datetime.now().isoformat(),
        error_message,
        node_name,
        'FALSE'
    ]]
    sheets_service.spreadsheets().values().append(
        spreadsheetId=GOOGLE_SPREADSHEET_ID,
        range='Processing_Errors!A:E',
        valueInputOption='RAW',
        body={'values': values}
    ).execute()
    logger.error(f"Logged error: {filename} - {error_message}")


# ============================================================================
# PDF PARSING
# ============================================================================

def extract_pdf_text(pdf_content: bytes) -> str:
    """Extract text from PDF content. Tries pdfplumber first, falls back to PyPDF2."""
    text = ""

    # Try pdfplumber first
    try:
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        if text.strip():
            return text.strip()
    except Exception as e:
        logger.warning(f"pdfplumber failed, trying PyPDF2: {e}")

    # Fallback to PyPDF2
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception as e:
        logger.error(f"PyPDF2 also failed: {e}")

    return text.strip()


def parse_filename(filename: str) -> Dict[str, str]:
    """
    Parse Fireflies filename to extract consultant name, candidate info, and date.

    Examples:
    - Killian_Dougal___1_929-229-1016__-__1_949-701-2278-transcript-2026-01-20T13-43-50_000Z.pdf
    - Sean_McDermott___44_131_381_5617__-__44_7933_158168-transcript-2026-01-20T13-43-55_000Z.pdf
    """
    result = {
        'consultantName': '',
        'candidateName': '',
        'callDate': datetime.now().strftime('%Y-%m-%d'),
        'fileName': filename
    }

    # Try to extract consultant name (before ___)
    if '___' in filename:
        consultant_part = filename.split('___')[0]
        result['consultantName'] = consultant_part.replace('_', ' ').strip()
    elif ' - ' in filename:
        # Alternative format: "+1 917-843-9780 - Reece Pearce [+1 929-492-2994]-transcript-..."
        parts = filename.split(' - ')
        if len(parts) >= 2:
            # Find the part with a name (contains letters)
            for part in parts:
                if re.search(r'[A-Za-z]{2,}', part):
                    # Extract name, removing phone numbers in brackets
                    name = re.sub(r'\[.*?\]', '', part).strip()
                    name = re.sub(r'[\+\d\-\(\)\s]+$', '', name).strip()
                    if name:
                        result['consultantName'] = name
                        break

    # Extract date from filename
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    if date_match:
        result['callDate'] = date_match.group(1)

    # Extract candidate info (phone number or name)
    # Look for phone numbers
    phone_match = re.search(r'[\+]?[\d\s\-]{10,}', filename)
    if phone_match:
        result['candidateName'] = phone_match.group(0).strip()

    return result


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


# ============================================================================
# AZURE OPENAI
# ============================================================================

def call_azure_openai(prompt_template: str, transcript: str, consultant_name: str = '', candidate_name: str = '') -> str:
    """Call Azure OpenAI to extract call notes."""

    # Build the full prompt
    full_prompt = prompt_template.replace('{{transcript_text}}', transcript)
    full_prompt = full_prompt.replace('{{recruiter_names}}', consultant_name)
    full_prompt = full_prompt.replace('{{candidate_names}}', candidate_name)

    url = f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"

    headers = {
        'Content-Type': 'application/json',
        'api-key': AZURE_OPENAI_API_KEY
    }

    body = {
        "messages": [
            {
                "role": "system",
                "content": "You are a recruitment call analyst for Meraki Talent, a UK-based financial services recruitment agency. Extract candidate information according to the provided template. Only include information explicitly stated by the candidate about themselves. Recruiter statements must be ignored. If information is not explicitly stated, write 'Not stated'. Do not infer or guess."
            },
            {
                "role": "user",
                "content": full_prompt
            }
        ],
        "temperature": 0.1,
        "max_tokens": 2000
    }

    response = requests.post(url, headers=headers, json=body, timeout=120)
    response.raise_for_status()

    data = response.json()
    return data['choices'][0]['message']['content']


# ============================================================================
# MICROSOFT GRAPH API
# ============================================================================

class GraphAPIClient:
    """Microsoft Graph API client with OAuth2 token management."""

    def __init__(self):
        self.access_token = None
        self.refresh_token = None
        self.token_expires = 0
        self._load_refresh_token()

    def _load_refresh_token(self):
        """Load refresh token from environment variable or file."""
        # First try environment variable (Railway)
        if MS_REFRESH_TOKEN:
            self.refresh_token = MS_REFRESH_TOKEN
            return

        # Fall back to file (local development)
        token_file = 'ms_refresh_token.txt'
        if os.path.exists(token_file):
            with open(token_file, 'r') as f:
                self.refresh_token = f.read().strip()

    def _save_refresh_token(self):
        """Save refresh token to file."""
        if self.refresh_token:
            with open('ms_refresh_token.txt', 'w') as f:
                f.write(self.refresh_token)

    def _refresh_access_token(self):
        """Refresh the access token using refresh token."""
        if not self.refresh_token:
            raise Exception("No refresh token available. Please authenticate first.")

        url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token"

        data = {
            'client_id': MS_CLIENT_ID,
            'client_secret': MS_CLIENT_SECRET,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
            'scope': 'Chat.Create ChatMessage.Send User.Read offline_access'
        }

        response = requests.post(url, data=data)
        response.raise_for_status()

        tokens = response.json()
        self.access_token = tokens['access_token']
        self.token_expires = time.time() + tokens.get('expires_in', 3600) - 60

        if 'refresh_token' in tokens:
            self.refresh_token = tokens['refresh_token']
            self._save_refresh_token()

        logger.info("Access token refreshed successfully")

    def get_access_token(self) -> str:
        """Get valid access token, refreshing if necessary."""
        if not self.access_token or time.time() >= self.token_expires:
            self._refresh_access_token()
        return self.access_token

    def create_chat(self, recipient_user_id: str) -> str:
        """Create a 1:1 chat with a user. Returns chat ID."""
        url = "https://graph.microsoft.com/v1.0/chats"

        headers = {
            'Authorization': f'Bearer {self.get_access_token()}',
            'Content-Type': 'application/json'
        }

        body = {
            "chatType": "oneOnOne",
            "members": [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{JOEL_AAD_ID}"
                },
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{recipient_user_id}"
                }
            ]
        }

        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()

        return response.json()['id']

    def send_adaptive_card(self, chat_id: str, card: dict, fallback_text: str = "Call Notes"):
        """Send an adaptive card to a chat."""
        url = f"https://graph.microsoft.com/v1.0/chats/{chat_id}/messages"

        headers = {
            'Authorization': f'Bearer {self.get_access_token()}',
            'Content-Type': 'application/json'
        }

        body = {
            "body": {
                "contentType": "html",
                "content": '<attachment id="ac1"></attachment>'
            },
            "attachments": [
                {
                    "id": "ac1",
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": json.dumps(card)
                }
            ]
        }

        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()

        logger.info(f"Message sent to chat {chat_id}")


def build_adaptive_card(candidate_name: str, call_date: str, notes: str, filename: str) -> dict:
    """Build an Adaptive Card with the call notes."""
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "body": [
            {
                "type": "TextBlock",
                "text": f"Call Notes: {candidate_name}",
                "weight": "Bolder",
                "size": "Large"
            },
            {
                "type": "TextBlock",
                "text": f"Date: {call_date}",
                "size": "Medium",
                "spacing": "Small"
            },
            {
                "type": "TextBlock",
                "text": notes,
                "wrap": True,
                "spacing": "Medium"
            },
            {
                "type": "TextBlock",
                "text": f"Source: {filename}",
                "size": "Small",
                "isSubtle": True,
                "spacing": "Large"
            }
        ]
    }


# ============================================================================
# MAIN PROCESSOR
# ============================================================================

def process_single_file(
    drive_service,
    sheets_service,
    graph_client: GraphAPIClient,
    file: dict,
    consultants: dict,
    prompts: dict
):
    """Process a single PDF file."""

    file_id = file['id']
    filename = file['name']

    logger.info(f"Processing: {filename}")

    try:
        # 1. Download PDF
        pdf_content = download_pdf(drive_service, file_id)

        # 2. Extract text
        transcript = extract_pdf_text(pdf_content)
        word_count = count_words(transcript)

        logger.info(f"Extracted {word_count} words from {filename}")

        # 3. Parse filename
        file_info = parse_filename(filename)
        consultant_name = file_info['consultantName']

        # 4. Word count gate
        if word_count < WORD_COUNT_THRESHOLD:
            log_skipped_call(sheets_service, filename, word_count, "Too short", consultant_name)
            rename_processed_file(drive_service, file_id, filename)
            return

        # 5. Lookup consultant
        consultant = consultants.get(consultant_name.lower())

        if not consultant:
            log_skipped_call(sheets_service, filename, word_count, "Unknown consultant", consultant_name)
            rename_processed_file(drive_service, file_id, filename)
            return

        if not consultant['Active']:
            log_skipped_call(sheets_service, filename, word_count, "Inactive consultant", consultant_name)
            rename_processed_file(drive_service, file_id, filename)
            return

        teams_user_id = consultant['TeamsUserId']
        desk = consultant['Desk']

        if not teams_user_id:
            log_skipped_call(sheets_service, filename, word_count, "No TeamsUserId", consultant_name)
            rename_processed_file(drive_service, file_id, filename)
            return

        # 6. Get desk prompt
        prompt_template = prompts.get(desk)
        if not prompt_template:
            # Use default/fallback prompt
            prompt_template = prompts.get('Default', 'Please summarize this call transcript:\n\n{{transcript_text}}')

        # 7. Call Azure OpenAI
        logger.info(f"Calling Azure OpenAI for {filename}")
        notes = call_azure_openai(
            prompt_template,
            transcript,
            consultant_name,
            file_info['candidateName']
        )

        # 8. Build adaptive card
        card = build_adaptive_card(
            file_info['candidateName'],
            file_info['callDate'],
            notes,
            filename
        )

        # 9. Send Teams message
        logger.info(f"Sending Teams message to {consultant_name} ({teams_user_id})")
        chat_id = graph_client.create_chat(teams_user_id)
        graph_client.send_adaptive_card(chat_id, card)

        # 10. Rename processed file
        rename_processed_file(drive_service, file_id, filename)

        logger.info(f"Successfully processed: {filename}")

    except Exception as e:
        import traceback
        logger.error(f"Error processing {filename}: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        log_processing_error(sheets_service, filename, str(e), "process_single_file")


def run_once():
    """Run a single processing cycle."""
    logger.info("-" * 40)
    logger.info("Starting processing cycle...")

    # Initialize services
    drive_service, sheets_service = get_google_services()
    graph_client = GraphAPIClient()

    # Load configuration from sheets (refreshed each cycle)
    consultants = get_consultants(sheets_service)
    prompts = get_prompts(sheets_service)
    logger.info(f"Loaded {len(consultants)} consultants, {len(prompts)} prompts")
    if prompts:
        logger.info(f"Prompt desks: {list(prompts.keys())}")

    # Get new files
    files = get_new_pdf_files(drive_service)

    if not files:
        logger.info("No new files to process")
        return 0

    logger.info(f"Found {len(files)} new files to process")

    # Process each file
    processed = 0
    for file in files:
        try:
            process_single_file(
                drive_service,
                sheets_service,
                graph_client,
                file,
                consultants,
                prompts
            )
            processed += 1
        except Exception as e:
            logger.error(f"Failed to process {file['name']}: {e}")

    logger.info(f"Cycle complete. Processed {processed}/{len(files)} files.")
    return processed


def main():
    """Main entry point with polling loop."""
    # Configuration
    POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', 300))  # Default 5 minutes

    logger.info("=" * 60)
    logger.info("Meraki Call Notes Processor")
    logger.info(f"Poll interval: {POLL_INTERVAL} seconds")
    logger.info("=" * 60)

    # Run continuously
    while True:
        try:
            run_once()
        except Exception as e:
            logger.error(f"Error in processing cycle: {e}")

        logger.info(f"Sleeping for {POLL_INTERVAL} seconds...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
