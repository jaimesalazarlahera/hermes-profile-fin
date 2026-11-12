import os
import json

import google.auth
from googleapiclient.discovery import build

TOKEN = "/opt/data/google_token.json"
SPREADSHEET_ID = "1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0"

creds, _ = google.auth.load_credentials_from_file(TOKEN)
service = build("sheets", "v4", credentials=creds)

for tab in ["Research Log", "Orders", "Positions", "Watchlist"]:
    try:
        v = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=tab + "!A1:Z20").execute()
        rows = v.get("values", [])
        print("=== SHEET:", tab, "rows:", len(rows))
        for r in rows[:20]:
            print("  ", r)
    except Exception as e:
        print("=== SHEET:", tab, "ERR", e)
