import os
os.environ.setdefault("HERMES_HOME", "/opt/data")
from google.auth import load_credentials_from_file
creds, _ = load_credentials_from_file("/opt/data/google_token.json")
from googleapiclient.discovery import build
service = build("sheets", "v4", credentials=creds)
spreadsheet_id = "1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0"
# list spreadsheets / tabs
try:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    print("SHEETS_TABS:", [ (t.get("properties",{}).get("title"), t.get("properties",{}).get("gridProperties",{}).get("rowCount")) for t in meta.get("sheets",[]) ])
    for tab in meta.get("sheets",[]):
        title = tab.get("properties",{}).get("title")
        try:
            rows = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=title, majorDimension="ROWS").execute().get("values",[])
            print(f"--- {title} ({len(rows)} rows) ---")
            for r in rows[:8]:
                print(r)
        except Exception as e:
            print("ERR", title, type(e).__name__, e)
except Exception as e:
    print("ERR sheets get", type(e).__name__, e)
