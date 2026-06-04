"""One-time OAuth2 flow to mint a refresh token for the proforma_bot.

Mirrors call-notes-bot/auth_setup.py but with MAIL-READ scopes. Run locally:
    python -m proforma_bot.auth_setup

Sign in as Joel (the account with delegated access to the meraki1 shared
mailbox). The resulting refresh token goes into ms_refresh_token.txt; copy it
into Railway as MS_REFRESH_TOKEN.
"""
import os
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

MS_TENANT_ID = os.environ.get("MS_TENANT_ID", "")
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8765/callback"
SCOPES = "Mail.Read.Shared Mail.ReadBasic.Shared Mail.Send.Shared User.Read offline_access"


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        if "code" in params:
            auth_code = params["code"][0]
            token_url = (
                f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token"
            )
            data = {
                "client_id": MS_CLIENT_ID,
                "client_secret": MS_CLIENT_SECRET,
                "code": auth_code,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
                "scope": SCOPES,
            }
            r = requests.post(token_url, data=data, timeout=30)
            if r.status_code == 200:
                refresh_token = r.json().get("refresh_token")
                with open("ms_refresh_token.txt", "w") as f:
                    f.write(refresh_token)
                print("\nSUCCESS — refresh token saved to ms_refresh_token.txt")
                print("Set MS_REFRESH_TOKEN on Railway to that value.")
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Success.</h1><p>You can close this window.</p>")
            else:
                print(f"\nToken exchange failed: {r.text}")
                self.send_response(400)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(f"<pre>{r.text}</pre>".encode())
        elif "error" in params:
            err = params.get("error", ["?"])[0]
            desc = params.get("error_description", [""])[0]
            print(f"\nAuth error: {err} — {desc}")
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h1>{err}</h1><p>{desc}</p>".encode())
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>No code received</h1>")

        self.server.shutdown_flag = True  # type: ignore[attr-defined]

    def log_message(self, format, *args):
        pass


def main() -> None:
    auth_url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/authorize"
    params = {
        "client_id": MS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "response_mode": "query",
    }
    full_url = f"{auth_url}?{urllib.parse.urlencode(params)}"
    print("Opening browser for sign-in. Sign in as Joel.")
    print(f"If the browser doesn't open: {full_url}")
    webbrowser.open(full_url)

    server = HTTPServer(("localhost", 8765), CallbackHandler)
    server.shutdown_flag = False  # type: ignore[attr-defined]
    while not server.shutdown_flag:  # type: ignore[attr-defined]
        server.handle_request()
    server.server_close()


if __name__ == "__main__":
    main()
