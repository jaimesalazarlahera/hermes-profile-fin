import json
import sys

# Find the token file under the poe profile
home_candidates = [
    "/opt/data/profiles/poe/google_token.json",
    "/opt/data/google_token.json",
    "/opt/data/profiles/poe/.hermes/google_token.json",
]
token_path = None
for c in home_candidates:
    try:
        with open(c) as f:
            json.load(f)
        token_path = c
        break
    except Exception:
        continue
print("token_path:", token_path)

try:
    import gspread
    print("gspread version:", gspread.__version__)
    gc = gspread.authorize(gspread.service_account(filename=token_path))
    sh = gc.open_by_key("1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0")
    print("spreadsheet title:", sh.title)
    for ws in sh.worksheets():
        print("SHEET:", ws.title, "dims:", ws.dimensions, "rows:", ws.row_count, "cols:", ws.col_count)
        # print first 3 rows if small
        try:
            for r in ws.get_all_values()[:3]:
                print("  row:", r)
        except Exception as e:
            print("  err", e)
except Exception as e:
    print("ERR:", type(e).__name__, e)
    sys.exit(1)
