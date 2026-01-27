"""
Setup Private Channels for Call Notes

Creates a Team with private channels for each consultant.
Each consultant is added as owner of their channel.
Channel IDs are saved back to Google Sheets.

Run once after updating OAuth token with new scopes:
1. Run: python auth_setup.py (sign in as Joel)
2. Run: python setup_channels.py
"""

import os
import json
import time
import base64
import logging
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ============================================================================
# CONFIGURATION
# ============================================================================

GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "meraki-n8n-automation-66a9d5aafc1e.json")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SPREADSHEET_ID = os.environ.get("GOOGLE_SPREADSHEET_ID", "1Z_5rhbhe4lW13t4DKOzhWW-cKLbeyneUHTZXBUmBM-g")

MS_TENANT_ID = os.environ.get("MS_TENANT_ID", "")
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET", "")
MS_REFRESH_TOKEN = os.environ.get("MS_REFRESH_TOKEN", "")
JOEL_AAD_ID = os.environ.get("JOEL_AAD_ID", "")

TEAM_NAME = "Call Notes"
TEAM_DESCRIPTION = "Automated call notes from recruitment calls"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# GOOGLE SHEETS
# ============================================================================

def get_sheets_service():
    """Initialize Google Sheets service."""
    scopes = ['https://www.googleapis.com/auth/spreadsheets']

    if GOOGLE_SERVICE_ACCOUNT_JSON:
        json_str = GOOGLE_SERVICE_ACCOUNT_JSON
        try:
            json_str = base64.b64decode(json_str).decode('utf-8')
        except Exception:
            pass
        service_account_info = json.loads(json_str)
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=scopes
        )
    else:
        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes
        )

    return build('sheets', 'v4', credentials=credentials)


def get_consultants(sheets_service):
    """Load consultants from Google Sheets."""
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=GOOGLE_SPREADSHEET_ID,
        range='Consultants!A:F'  # Extended to include ChannelId column
    ).execute()
    rows = result.get('values', [])

    if not rows:
        return []

    headers = rows[0]
    consultants = []

    for i, row in enumerate(rows[1:], start=2):  # Start at row 2 (1-indexed)
        if len(row) >= 4:
            consultants.append({
                'row': i,
                'Name': row[0].strip() if len(row) > 0 else '',
                'Email': row[1] if len(row) > 1 else '',
                'Desk': row[2] if len(row) > 2 else '',
                'TeamsUserId': row[3] if len(row) > 3 else '',
                'Active': row[4].upper() == 'TRUE' if len(row) > 4 else False,
                'ChannelId': row[5] if len(row) > 5 else ''
            })

    return consultants


def update_channel_id(sheets_service, row: int, channel_id: str):
    """Update ChannelId for a consultant in Google Sheets."""
    sheets_service.spreadsheets().values().update(
        spreadsheetId=GOOGLE_SPREADSHEET_ID,
        range=f'Consultants!F{row}',
        valueInputOption='RAW',
        body={'values': [[channel_id]]}
    ).execute()
    logger.info(f"Updated row {row} with ChannelId: {channel_id}")


# ============================================================================
# MICROSOFT GRAPH API
# ============================================================================

class GraphClient:
    """Microsoft Graph API client."""

    def __init__(self):
        self.access_token = None
        self.token_expires = 0
        self._load_refresh_token()

    def _load_refresh_token(self):
        """Load refresh token."""
        if MS_REFRESH_TOKEN:
            self.refresh_token = MS_REFRESH_TOKEN
        else:
            if os.path.exists('ms_refresh_token.txt'):
                with open('ms_refresh_token.txt', 'r') as f:
                    self.refresh_token = f.read().strip()
            else:
                self.refresh_token = None

    def _refresh_access_token(self):
        """Refresh access token."""
        if not self.refresh_token:
            raise Exception("No refresh token. Run auth_setup.py first.")

        url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token"
        data = {
            'client_id': MS_CLIENT_ID,
            'client_secret': MS_CLIENT_SECRET,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
            'scope': 'Chat.Create ChatMessage.Send ChannelMessage.Send Channel.Create Team.Create Team.ReadBasic.All ChannelMember.ReadWrite.All User.Read offline_access'
        }

        response = requests.post(url, data=data)
        response.raise_for_status()

        tokens = response.json()
        self.access_token = tokens['access_token']
        self.token_expires = time.time() + tokens.get('expires_in', 3600) - 60

        if 'refresh_token' in tokens:
            self.refresh_token = tokens['refresh_token']
            with open('ms_refresh_token.txt', 'w') as f:
                f.write(self.refresh_token)

        logger.info("Access token refreshed")

    def get_token(self):
        """Get valid access token."""
        if not self.access_token or time.time() >= self.token_expires:
            self._refresh_access_token()
        return self.access_token

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.get_token()}',
            'Content-Type': 'application/json'
        }

    def get_joined_teams(self):
        """Get teams the user has joined."""
        url = "https://graph.microsoft.com/v1.0/me/joinedTeams"
        response = requests.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json().get('value', [])

    def create_team(self, name: str, description: str) -> str:
        """Create a new Team. Returns team ID."""
        url = "https://graph.microsoft.com/v1.0/teams"
        body = {
            "template@odata.bind": "https://graph.microsoft.com/v1.0/teamsTemplates('standard')",
            "displayName": name,
            "description": description
        }

        response = requests.post(url, headers=self._headers(), json=body)

        if response.status_code == 202:
            # Team creation is async - get team ID from location header
            location = response.headers.get('Content-Location', '')
            # Location format: /teams('team-id')
            if location:
                team_id = location.split("'")[1] if "'" in location else location.split('/')[-1]
                logger.info(f"Team creation started, ID: {team_id}")
                return team_id
            else:
                # Wait and find the team by name
                logger.info("Waiting for team creation...")
                time.sleep(10)
                teams = self.get_joined_teams()
                for team in teams:
                    if team['displayName'] == name:
                        return team['id']
                raise Exception("Could not find created team")
        else:
            response.raise_for_status()

    def get_team_channels(self, team_id: str):
        """Get channels in a team."""
        url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels"
        response = requests.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json().get('value', [])

    def create_private_channel(self, team_id: str, channel_name: str, owner_user_id: str) -> str:
        """Create a private channel with the consultant as owner. Returns channel ID."""
        url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels"

        body = {
            "displayName": channel_name,
            "description": f"Call notes for {channel_name}",
            "membershipType": "private",
            "members": [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{JOEL_AAD_ID}",
                    "roles": ["owner"]
                },
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{owner_user_id}",
                    "roles": ["owner"]
                }
            ]
        }

        response = requests.post(url, headers=self._headers(), json=body)
        response.raise_for_status()

        channel = response.json()
        return channel['id']

    def send_channel_message(self, team_id: str, channel_id: str, content: str):
        """Send a text message to a channel."""
        url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages"
        body = {
            "body": {
                "content": content
            }
        }
        response = requests.post(url, headers=self._headers(), json=body)
        response.raise_for_status()


# ============================================================================
# MAIN SETUP
# ============================================================================

def main():
    """Set up Team and private channels for all consultants."""
    logger.info("=" * 60)
    logger.info("Call Notes Channel Setup")
    logger.info("=" * 60)

    # Initialize services
    sheets_service = get_sheets_service()
    graph = GraphClient()

    # Check for existing team or create new one
    logger.info(f"Looking for existing '{TEAM_NAME}' team...")
    teams = graph.get_joined_teams()

    team_id = None
    for team in teams:
        if team['displayName'] == TEAM_NAME:
            team_id = team['id']
            logger.info(f"Found existing team: {team_id}")
            break

    if not team_id:
        logger.info(f"Creating new team: {TEAM_NAME}")
        team_id = graph.create_team(TEAM_NAME, TEAM_DESCRIPTION)
        logger.info(f"Created team: {team_id}")
        logger.info("Waiting for team provisioning...")
        time.sleep(30)  # Wait for team to be fully provisioned

    # Get existing channels
    existing_channels = graph.get_team_channels(team_id)
    existing_names = {ch['displayName']: ch['id'] for ch in existing_channels}
    logger.info(f"Existing channels: {list(existing_names.keys())}")

    # Load consultants
    consultants = get_consultants(sheets_service)
    logger.info(f"Loaded {len(consultants)} consultants")

    # Create channels for active consultants without a channel
    created = 0
    skipped = 0

    for consultant in consultants:
        name = consultant['Name']
        teams_user_id = consultant['TeamsUserId']
        active = consultant['Active']
        existing_channel_id = consultant['ChannelId']
        row = consultant['row']

        if not active:
            logger.info(f"Skipping {name} (inactive)")
            skipped += 1
            continue

        if not teams_user_id:
            logger.info(f"Skipping {name} (no TeamsUserId)")
            skipped += 1
            continue

        # Check if channel already exists
        if name in existing_names:
            channel_id = existing_names[name]
            logger.info(f"Channel already exists for {name}: {channel_id}")
            if not existing_channel_id:
                update_channel_id(sheets_service, row, channel_id)
            continue

        if existing_channel_id:
            logger.info(f"Skipping {name} (already has ChannelId: {existing_channel_id})")
            continue

        # Create private channel
        try:
            logger.info(f"Creating private channel for {name}...")
            channel_id = graph.create_private_channel(team_id, name, teams_user_id)
            logger.info(f"Created channel: {channel_id}")

            # Update Google Sheet
            update_channel_id(sheets_service, row, channel_id)

            # Send welcome message
            graph.send_channel_message(
                team_id,
                channel_id,
                f"Welcome to your Call Notes channel, {name}! Your automated call summaries will appear here."
            )

            created += 1

            # Rate limiting - wait between channel creations
            time.sleep(2)

        except Exception as e:
            logger.error(f"Failed to create channel for {name}: {e}")

    # Summary
    logger.info("=" * 60)
    logger.info("Setup Complete")
    logger.info(f"Team ID: {team_id}")
    logger.info(f"Channels created: {created}")
    logger.info(f"Skipped: {skipped}")
    logger.info("=" * 60)

    # Save team ID for reference
    with open('team_id.txt', 'w') as f:
        f.write(team_id)
    logger.info("Team ID saved to team_id.txt")

    print(f"\nNext steps:")
    print(f"1. Add TEAM_ID={team_id} to Railway environment variables")
    print(f"2. Redeploy to Railway (git push)")
    print(f"3. The processor will now post to private channels instead of 1:1 chats")


if __name__ == "__main__":
    main()
