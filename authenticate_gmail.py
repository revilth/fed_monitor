"""
One-time Gmail OAuth2 authorization.

Run this once:
    python3 authenticate_gmail.py

It will open a browser window asking you to authorize access to your Gmail.
After you click Allow, a token.json file is saved locally. The daily email
script uses that token automatically from then on — no further interaction needed.

SETUP (do this before running):
1. Go to https://console.cloud.google.com
2. Create a project (or select an existing one)
3. Enable the Gmail API: APIs & Services → Enable APIs → search "Gmail API" → Enable
4. Create credentials: APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: Desktop app
   - Name: Fed Monitor
5. Download the JSON file and save it as:
   /Users/revilth/Documents/Research_Claude/Monitoring_Fed/credentials.json
6. Run this script: python3 authenticate_gmail.py
"""

from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import json

BASE_DIR = Path(__file__).parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"

# Only need send scope — not full Gmail access
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def authenticate():
    if not CREDENTIALS_FILE.exists():
        print(f"\nERROR: credentials.json not found at {CREDENTIALS_FILE}")
        print("\nSetup steps:")
        print("1. Go to https://console.cloud.google.com")
        print("2. Enable Gmail API (APIs & Services → Enable APIs → Gmail API)")
        print("3. Create OAuth credentials (Desktop app type)")
        print("4. Download JSON → save as credentials.json in this folder")
        print("5. Re-run this script")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json())
    print(f"\nSuccess! Token saved to {TOKEN_FILE}")
    print("The daily email script will now run automatically.")


if __name__ == "__main__":
    authenticate()
