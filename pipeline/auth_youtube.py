"""
Dev Life with Uche — YouTube OAuth Setup

Standalone script to authenticate with YouTube API.
Opens a browser for Google OAuth consent, saves credentials,
and verifies the authenticated channel.

Usage:
    python auth_youtube.py
"""
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

CLIENT_SECRET_PATH = Path("./client_secret.json")
CREDENTIALS_PATH = Path.home() / ".dev-life-credentials.json"


def main():
    if not CLIENT_SECRET_PATH.exists():
        print(f"ERROR: {CLIENT_SECRET_PATH.resolve()} not found.")
        print("Download it from Google Cloud Console -> APIs & Services -> Credentials")
        raise SystemExit(1)

    creds = None
    if CREDENTIALS_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(CREDENTIALS_PATH), SCOPES)

    if creds and creds.valid:
        print(f"Existing credentials found at {CREDENTIALS_PATH}")
    elif creds and creds.expired and creds.refresh_token:
        print("Refreshing expired credentials...")
        creds.refresh(Request())
        CREDENTIALS_PATH.write_text(creds.to_json())
        print("Credentials refreshed.")
    else:
        print("Opening browser for Google OAuth consent...")
        print("Make sure you are logged into the Dev Life with Uche Google account.\n")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
        creds = flow.run_local_server(port=0)
        CREDENTIALS_PATH.write_text(creds.to_json())
        print(f"\nCredentials saved to {CREDENTIALS_PATH}")

    print("\nVerifying channel access...")
    youtube = build("youtube", "v3", credentials=creds)
    resp = youtube.channels().list(part="snippet", mine=True).execute()

    items = resp.get("items", [])
    if not items:
        print("ERROR: No YouTube channel found for these credentials.")
        print(f"Delete {CREDENTIALS_PATH} and re-run to try a different account.")
        raise SystemExit(1)

    channel = items[0]
    print(f"\n  Channel: {channel['snippet']['title']}")
    print(f"  ID:      {channel['id']}")
    print(f"\n  YouTube OAuth setup complete.")


if __name__ == "__main__":
    main()
