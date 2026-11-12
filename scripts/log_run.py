import os
os.environ.setdefault("HERMES_HOME", "/opt/data")
from google.auth import load_credentials_from_file
creds, _ = load_credentials_from_file("/opt/data/google_token.json")
from googleapiclient.discovery import build
service = build("sheets", "v4", credentials=creds)
SPREADSHEET_ID = "1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0"
NOW = "2026-11-11 15:13:03"
row = [
    NOW,
    "VWCEd_EQ;VUAAm_EQ;CEBZd_EQ",
    "HOLD",
    "No new order this run. Candle (Yahoo, as_of 2026-11-11, 0d stale): VWCEd_EQ 170.48 [sma20 169.56/sma50 169.47/sma200 160.46, rsi 53.3, above 200d]; VUAAm_EQ 132.41 [132.18/131.31/123.04, rsi 50.1, above 200d]; CEBZd_EQ 7.06 [6.91/6.84/6.66, rsi 69.6]. Market: JPM 2026 constructive, US AI concentration risk 'winner-takes-all'; Eurozone EPS +13%+. Decision: no new order - the 3 pending staged buys (VWCEd 5.2@165.5, VUAAm 1.9@128.2, CEBZd 142.0@7.0; blocked 2098.18) already build the diversified EUR core; a satellite would over-concentrate, and JPM's concentration warning argues against more single-flow exposure.",
    "https://www.jpmorgan.com/insights/global-research/outlook/market-outlook | https://finance.yahoo.com/quote/VWCE.DE | https://finance.yahoo.com/quote/VUAA.DE | https://finance.yahoo.com/quote/CEBZ.DE | https://www.trading212.com/"
]
body = {"values": [row]}
try:
    res = service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID, range="Research Log",
        valueInputOption="USER_ENTERED", body=body).execute()
    print("Research Log appended:", res.get("updates",{}).get("updatedRows"), "rows")
except Exception as e:
    print("ERR append Research Log", type(e).__name__, e)
