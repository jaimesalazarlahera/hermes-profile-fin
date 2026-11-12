import os
import json

import google.auth
from googleapiclient.discovery import build

TOKEN = "/opt/data/google_token.json"
SPREADSHEET_ID = "1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0"

creds, _ = google.auth.load_credentials_from_file(TOKEN)
service = build("sheets", "v4", credentials=creds)

def show(label, req):
    r = req.execute()
    print(label, "=>", json.dumps(r)[:1500])
    print("---")

# 1. title
show("title", service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID, fields="properties(title)"))
# 2. sheets list
show("sheets", service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID, fields="sheets(properties(title))"))
