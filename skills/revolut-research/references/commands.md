# Revolut Research: Reference commands

Exact commands for common operations in the Revolut Research & Holdings pipeline.

---

## Environment & auth

```bash
# Set HERMES_HOME (the poe profile's HERMES_HOME is /opt/data)
export HERMES_HOME=/opt/data

# Check the active Hermes home
python3 -c "from hermes_constants import get_hermes_home; print(get_hermes_home())"

# Refresh the OAuth token (after expiry)
cd /opt/data && /opt/hermes/.venv/bin/python - <<'PYEOF'
from google.oauth2.credentials import Credentials as OAuthCredentials
creds = OAuthCredentials.from_authorized_user_file("google_token.json", ["https://www.googleapis.com/auth/spreadsheets"])
creds.refresh(OAuthCredentials._client)  # uses the refresh token
with open("google_token.json", "w") as f:
    f.write(creds.to_json())
PYEOF
```

---

## Google Sheets: get a tab's contents

```bash
# Get the Research Log tab (all rows)
/opt/hermes/.venv/bin/python /opt/hermes/skills/productivity/google-workspace/scripts/google_api.py \
  sheets get 1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0 "Research Log!A:G"

# Get the Watchlist tab (full contents)
/opt/hermes/.venv/bin/python /opt/hermes/skills/productivity/google-workspace/scripts/google_api.py \
  sheets get 1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0 "Watchlist!A:G"

# Get the Orders tab (full contents)
/opt/hermes/.venv/bin/python /opt/hermes/skills/productivity/google-workspace/scripts/google_api.py \
  sheets get 1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0 "Orders!A:G"
```

---

## Google Sheets: batch update (set number format to unlock date picker)

```bash
/opt/hermes/.venv/bin/python /opt/hermes/skills/productivity/google-workspace/scripts/google_api.py \
  sheets batch_update 1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0 \
  --body '{"requests":[{"repeatCell":{"range":{"sheetId":956741081,"startRowIndex":1,"endRowIndex":6,"startColumnIndex":0,"endColumnIndex":1},"cell":{"userEnteredFormat":{"numberFormat":{"type":"DATE_TIME","format":"yyyy-mm-dd hh:mm:ss"}}}}}}]'
```

Note: `sheetId` for the Research Log tab is `956741081`. Verify with `sheets get` and check the `properties.sheetId` for each tab.

---

## Cron: list jobs

```bash
cronjob_manage list          # from the default store
cronjob_manage list cron     # if supported by the CLI
```

If `cronjob_manage list` returns `count: 0, jobs: []` but the job is known to exist, inspect `/opt/data/cron/jobs.json` directly:

```bash
cat /opt/data/cron/jobs.json | python3 -m json.tool
```

---

## Cron: trigger a job manually

```python
# via a Python one-liner
from cron.jobs import get_job, claim_job_for_fire
from cron.scheduler import run_one_job
job = get_job("1333b450797a")
claimed = claim_job_for_fire("1333b450797a", manual=True, return_job=True)
if claimed:
    run_one_job(claimed, verbose=False)
```

---

## Cron: run the research_pass.py script

```bash
cd /opt/data/scripts
export HERMES_HOME=/opt/data
/opt/hermes/.venv/bin/python research_pass.py 2>&1 | tail -30
```

The script is idempotent: `log_tickers_researched(today)` detects already-researched tickers by date+ticker and skips them. To reset the Research Log first, set `RESET_LOG=1` before running the script.

---

## Google Sheets: verify the date picker is unlocked

```bash
# Get the Research Log tab
/opt/hermes/.venv/bin/python /opt/hermes/skills/productivity/google-workspace/scripts/google_api.py \
  sheets get 1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0 "Research Log!A:G"
```

Check that:
1. The date column values are serial numbers (e.g. `46333.886516203704`), not strings.
2. The number format on the date column is `yyyy-mm-dd hh:mm:ss` (verify via a follow-up `sheets.get` request if needed).

---

## Google Sheets: list tab names and sheetIds

```python
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials as OAuthCredentials
creds = OAuthCredentials.from_authorized_user_file("google_token.json", ["https://www.googleapis.com/auth/spreadsheets"])
svc = build("sheets", "v4", credentials=creds)
resp = svc.spreadsheets().get(spreadsheetId="1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0").execute()
for sh in resp.get("sheets", []):
    print(sh["properties"]["title"], "->", sh["properties"]["sheetId"])
```

---

## Debug: "cron job says not found"

```bash
# Inspect both stores
cat /opt/data/cron/jobs.json | python3 -m json.tool
```

If `cronjob_manage list` returns `count: 0, jobs: []` but `get_job(id)` reports `enabled: True, state: scheduled`, the job is stored in the default store (`/opt/data/cron/jobs.json`), not the current profile's store.

---

## Debug: script runs but writes no rows

```bash
# Check the interpreter
/opt/hermes/.venv/bin/python --version
python3 --version

# Verify the venv has the needed packages
/opt/hermes/.venv/bin/python -c "import googleapiclient, httpx, bs4; print('ok')"
```

Use the absolute venv interpreter in any subprocess command:
```bash
"/opt/hermes/.venv/bin/python /opt/hermes/skills/productivity/google-workspace/scripts/google_api.py"
```

---

## Debug: token expired / "Not authenticated"

```bash
# Check the token's expiry
cd /opt/data && /opt/hermes/.venv/bin/python -c "
import json, datetime
d = json.load(open('google_token.json'))
exp = d.get('expiry')
print('expiry:', exp)
print('datetime:', datetime.datetime.fromisoformat(exp))
"
```

If expired, refresh the token with the refresh flow. Verify the token is written back to `google_token.json` with a new expiry.

---

## Debug: script runs successfully (final state)

```bash
# Job state
python3 -c "from cron.jobs import get_job; j = get_job('1333b450797a'); print(j['last_status'], j.get('last_run_at'))"

# Research Log
/opt/hermes/.venv/bin/python /opt/hermes/skills/productivity/google-workspace/scripts/google_api.py \
  sheets get 1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0 "Research Log!A:G"
```

Expected Research Log rows (5 active tickers):
- NVDA → BUY (order written)
- AAPL → HOLD
- SPCX → BUY (order written)
- VUAA → HOLD
- VWCE → HOLD

All date column values should be serial numbers, not strings.
