"""
One-time script to authorise Gmail access and save token.json.

Run once:
    python gmail_auth.py

This opens a browser for Google sign-in, then saves token.json
which the app uses for all subsequent Gmail calls.
"""

from google_auth_oauthlib.flow import InstalledAppFlow
import json, os

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]

if not os.path.exists("credentials.json"):
    print("ERROR: credentials.json not found.")
    print("Download it from Google Cloud Console > APIs & Services > Credentials")
    exit(1)

flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

with open("token.json", "w") as f:
    f.write(creds.to_json())

print("✓ token.json saved. You can now start the app.")
