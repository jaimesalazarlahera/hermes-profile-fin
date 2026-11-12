import os
import json
from datetime import datetime, timezone

import google.auth
from googleapiclient.discovery import build

TOKEN = "/opt/data/google_token.json"
SPREADSHEET_ID = "1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0"
NOW = datetime.now(timezone.utc).isoformat()

creds, _ = google.auth.load_credentials_from_file(TOKEN)
service = build("sheets", "v4", credentials=creds)

# ---- Orders tab rows (pending/new GTC buy orders) ----
orders_rows = [
    ["VWCEd_EQ", "BUY", 169.86, NOW, "", "", "", 0, 750.78, "", "57850376106"],
    ["VUAAm_EQ", "BUY", 131.85, NOW, "", "", "", 0, 499.71, "", "57850376108"],
]
body = {"values": orders_rows}
service.spreadsheets().values().append(
    spreadsheetId=SPREADSHEET_ID, range="Orders",
    valueInputOption="USER_ENTERED", body=body,
).execute()
print("Orders rows appended")

# ---- Research Log rows (candle analysis + orders decision) ----
res_rows = [
    ["11/11/2026 " + NOW[11:19], "VWCE", "BUY (limit, pending)",
     "Global core. STOOQ blocked; Yahoo fallback. VWCEd_EQ identifed via Trading 212 (ISIN IE00BK5BQT80, EUR, XETRA). Latest candle 2026-11-11; close 169.86; sma20 169.53 / sma50 169.46 / sma200 160.46; rsi 51.7; above 200d. Bought 4.42 @169.86 GTC.",
     "https://www.justetf.com/en/etf-profile.html?isin=IE00BK5BQT80 | https://finance.yahoo.com/quote/VWCE.DE/"],
    ["11/11/2026 " + NOW[11:19], "VUAA", "BUY (limit, pending)",
     "US tilt. VUAAm_EQ identifed via Trading 212 (ISIN IE00BFMXXD54, EUR, XETRA). Latest candle 2026-11-11; close 131.85; sma20 132.15 / sma50 131.30 / sma200 123.03; rsi 48.1; above 200d. Bought 3.79 @131.85 GTC.",
     "https://www.justetf.com/en/etf-profile.html?isin=IE00BFMXXD54 | https://finance.yahoo.com/quote/VUAA.DE/"],
]
body2 = {"values": res_rows}
service.spreadsheets().values().append(
    spreadsheetId=SPREADSHEET_ID, range="Research Log",
    valueInputOption="USER_ENTERED", body=body2,
).execute()
print("Research Log rows appended")
