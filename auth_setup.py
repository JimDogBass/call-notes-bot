"""
Microsoft Graph OAuth2 Setup
Run this once to get the refresh token for Teams messaging.
"""

import os
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

# Configuration - set these environment variables or edit directly for local use
MS_TENANT_ID = os.environ.get("MS_TENANT_ID", "")
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8765/callback"
SCOPES = "Chat.Create ChatMessage.Send ChannelMessage.Send Channel.Create Channel.ReadBasic.All Team.Create Team.ReadBasic.All ChannelMember.ReadWrite.All User.Read offline_access"


class CallbackHandler(BaseHTTPRequestHandler):
    """Handle OAuth callback."""

    def do_GET(self):
        """Handle GET request with auth code."""
        # Parse the authorization code from the URL
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        if 'code' in params:
            auth_code = params['code'][0]
            print(f"\nReceived authorization code!")

            # Exchange code for tokens
            token_url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token"

            data = {
                'client_id': MS_CLIENT_ID,
                'client_secret': MS_CLIENT_SECRET,
                'code': auth_code,
                'redirect_uri': REDIRECT_URI,
                'grant_type': 'authorization_code',
                'scope': SCOPES
            }

            response = requests.post(token_url, data=data)

            if response.status_code == 200:
                tokens = response.json()
                refresh_token = tokens.get('refresh_token')

                # Save refresh token
                with open('ms_refresh_token.txt', 'w') as f:
                    f.write(refresh_token)

                print("\n" + "=" * 60)
                print("SUCCESS! Refresh token saved to ms_refresh_token.txt")
                print("=" * 60)
                print("\nYou can now run: python call_notes_processor.py")

                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"<h1>Success!</h1><p>Refresh token saved. You can close this window.</p>")
            else:
                print(f"\nError getting tokens: {response.text}")
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(f"<h1>Error</h1><pre>{response.text}</pre>".encode())

        elif 'error' in params:
            error = params.get('error', ['Unknown'])[0]
            error_desc = params.get('error_description', [''])[0]
            print(f"\nAuth error: {error} - {error_desc}")
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(f"<h1>Error: {error}</h1><p>{error_desc}</p>".encode())

        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<h1>Error</h1><p>No authorization code received</p>")

        # Shutdown after handling
        self.server.shutdown_flag = True

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def main():
    """Run OAuth2 authorization flow."""
    print("=" * 60)
    print("Microsoft Graph OAuth2 Setup")
    print("=" * 60)

    # Build authorization URL
    auth_url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/authorize"
    params = {
        'client_id': MS_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
        'response_mode': 'query'
    }
    full_url = f"{auth_url}?{urllib.parse.urlencode(params)}"

    print(f"\nOpening browser for authentication...")
    print(f"Sign in as Joel (the account that will send messages)")
    print(f"\nIf browser doesn't open, visit:")
    print(full_url)

    # Open browser
    webbrowser.open(full_url)

    # Start local server to receive callback
    print(f"\nWaiting for callback on {REDIRECT_URI}...")

    server = HTTPServer(('localhost', 8765), CallbackHandler)
    server.shutdown_flag = False

    while not server.shutdown_flag:
        server.handle_request()

    server.server_close()


if __name__ == "__main__":
    main()
