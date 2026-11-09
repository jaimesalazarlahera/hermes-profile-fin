# Revolut Research: Pitfalls & debugging paths

Extended debugging paths and tool-usage patterns observed during this project.

---

## Google Sheets date picker is format-driven, not value-type-driven

**Rule:** The date/time picker is controlled by the cell's **number format**, not the underlying value type. String cells have no picker; date/datetime cells have a picker only when their number format is a date/datetime format.

**How to apply:**

1. Store actual date values (Excel 1900 serial numbers, e.g. `46333.886516203704`), NOT ISO strings (`"2026-11-07T21:16:35+00:00"`).
2. Send `sheets.batchUpdate` with a `repeatCell` request that sets `numberFormat.type = "DATE_TIME"` and `numberFormat.format = "yyyy-mm-dd hh:mm:ss"` on the date column for the rows just written.
3. The `repeatCell` range must cover the rows written (startRowIndex = 1 to skip the header, endRowIndex = 1 + number of rows, startColumnIndex = 0 for column A, endColumnIndex = 1).

**Why this works:** Google Sheets renders a cell as a date only when the number format's type is `DATE_TIME` or `DATE` and the cell value is numeric. A string cell can never show a picker, regardless of its content. Writing a serial number with a date format makes the cell a numeric date cell with a picker.

**Pitfall:** Writing serial numbers via `sheets.append` without a corresponding `batchUpdate` repeatCell → the cells are numeric but have the default "General" format, so no picker appears.

**Relevant script locations:**

- `to_serial(dt)` — Excel 1900 date system with leap-year-bug adjustment (`+1` for dates ≥ 1900-03-01).
- `write_log_row()` — converts `(date, ticker, sentiment, rationale, sources)` where `date` becomes a serial number.
- `log_rows` — stores `datetime.datetime.now(timezone.utc)` objects.
- Batch append block — converts each row's date to serial via `to_serial()` before `gapi(["sheets", "append", ...])`.
- Repeat-cell block — sends `sheets.batchUpdate` with `repeatCell` + `numberFormat.type = "DATE_TIME"` + `format = "yyyy-mm-dd hh:mm:ss"` on the Research Log date column.

---

## Debugging path: "cron job says not found"

**Rule:** If `cronjob_manage list` returns `count: 0, jobs: []` but `get_job(id)` reports `enabled: True, state: scheduled`, the job is stored in the default store (`/opt/data/cron/jobs.json`), not the current profile's store. Do not assume the profile's `jobs.json` is authoritative.

**How to apply:**

1. Inspect both stores: `/opt/data/cron/jobs.json` (default) and the profile's store (if any).
2. Run `cronjob_manage list` after pointing `HERMES_HOME` at the correct store.
3. Trigger via `claim_job_for_fire(job_id, manual=True, return_job=True)` then `run_one_job(claimed, verbose=False)` when the CLI refuses to resolve the job.

---

## Debugging path: "script runs but writes no rows"

**Rule:** `research_pass.py` must be run with the Hermes venv Python (`/opt/hermes/.venv/bin/python`), not the system Python. The system Python lacks `httpx`, `google-api-client`, and `beautifulsoup4`.

**How to apply:**

1. Check the interpreter: `/opt/hermes/.venv/bin/python --version` vs `python3 --version`.
2. Verify the venv has the needed packages: `/opt/hermes/.venv/bin/python -c "import googleapiclient, httpx, bs4"`.
3. Use the absolute venv interpreter in any subprocess command.

---

## Debugging path: `gapi` subprocess resolves to wrong interpreter

**Rule:** The cron worker PATH places a store venv before `/opt/hermes/.venv/bin`, so bare `python` resolves to a venv lacking Google packages. In cron jobs, the worker environment may differ from an interactive terminal.

**How to apply:**

1. Always use the absolute venv interpreter in subprocess commands, e.g. `"/opt/hermes/.venv/bin/python /opt/hermes/skills/productivity/google-workspace/scripts/google_api.py"`.
2. If the worker environment is uncertain, set `PATH` explicitly at the top of the script: `os.environ["PATH"] = "/opt/hermes/.venv/bin:/usr/local/bin:/usr/bin:/bin"`.

---

## Debugging path: Order rows not written (no BUY/SELL)

**Rule:** Order rows are written only when `write_order_row` is called for a BUY or SELL row. If all researched tickers got `HOLD` sentiment, no order rows are written.

**How to apply:**

1. Verify the model output includes `recommended_amount` and confidence.
2. Log the sentiment of each row; if all are `HOLD`, the script still writes log rows but no order rows.
3. The script writes to the `Orders` tab only when `sentiment in ("BUY", "SELL")`.

---

## Debugging path: Orders tab appears empty after run

**Rule:** The script appends to the `Orders` tab using the tab name (`ORDERS_TAB = "Orders"`). If the Orders tab was created with a different sheetId, the script still uses the tab name for appending, so the tab must still exist in the sheet with that name.

**How to apply:**

1. Verify the Orders tab exists in the sheet (list tabs with `google_api.py sheets get`).
2. Verify the tab name exactly matches `ORDERS_TAB = "Orders"` (case-sensitive).
3. The script appends using the tab name, not the sheetId.

---

## Debugging path: `log_tickers_researched` never triggers idempotency

**Rule:** `spreadsheets().get(range=...)` returns a keyed dict, not a `values` array. The check `spreadsheets().get(range=...)` returns a keyed response → always empty.

**How to apply:**

1. Use `_svc.spreadsheets().values().get(spreadsheetId, range="Research Log!A:G")` and compare `_row[0] == today`.
2. Iterate over the `values` array, not the keyed dict.
3. The date column (A) must contain the date string being checked (the script compares `_row[0] == today`).

---

## Debugging path: 12-ticker run hangs on one ticker

**Rule:** `build_digest` calls `web_extract_tool` on a market-data page (marketwatch.com) that extracts poorly; `ask_model` has no timeout.

**How to apply:**

1. Bound `run()` with `timeout=120`.
2. Bound `build_digest` extraction with 20s.
3. Skip market-data pages (marketwatch.com, etc.).
4. Set `ask_model` timeout to 90s.
5. If a ticker is skipped, collect it in a `skipped` list and print it at the end.

---

## Debugging path: ISO datetime strings do not show a date picker

**Rule:** The date picker is driven by the cell's number format, not the underlying value type. ISO strings are always treated as text and show no picker.

**How to apply (from this session):**

1. Convert datetime objects to Excel serial numbers via `to_serial()` (Excel 1900 date system with leap-year-bug adjustment for dates ≥ 1900-03-01).
2. Write serial numbers via `sheets.append` (the value is numeric, so it renders as a date cell).
3. Send `sheets.batchUpdate` with a `repeatCell` request to set `numberFormat.type = "DATE_TIME"` and `numberFormat.format = "yyyy-mm-dd hh:mm:ss"` on the date column for the rows written.
4. Skip the header row (startRowIndex = 1) and cover only the rows written (endRowIndex = 1 + number of rows).

**Verification:**

1. After the run, read the Research Log tab with `google_api.py sheets get`.
2. Check that the date column values are serial numbers (e.g. `46333.886516203704`), not strings.
3. Check that the number format is `yyyy-mm-dd hh:mm:ss` (verify via a follow-up `sheets.get` request if needed).

---

## Debugging path: Token expired / "Not authenticated"

**Rule:** `google_api.py` prints "Not authenticated. Run the setup script first" when the OAuth token is missing, invalid, or expired.

**How to apply:**

1. Check the token file: `$HERMES_HOME/google_token.json`. Verify it has `token`, `refresh_token`, `expires_at`, and `scopes`.
2. Parse the expiry: `datetime.fromisoformat(expiry)` — expiry is a timestamp, not a string; it is in UTC.
3. Refresh the token: use the refresh flow with `Credentials.refresh()` (the token URL is `https://oauth2.googleapis.com/token`).
4. Verify the token is written back to `google_token.json` with a new expiry.
5. Check scopes: the script needs `https://www.googleapis.com/auth/spreadsheets`.

---

## Debugging path: `google_api.py` cannot find the token

**Rule:** `google_api.py` uses `_hermes_home.py` to resolve `HERMES_HOME`. If `hermes_constants` is importable, it uses `get_hermes_home()` from there. Otherwise it falls back to `os.environ.get("HERMES_HOME", "")`.

**How to apply:**

1. Check `get_hermes_home()` in the venv: `/opt/hermes/.venv/bin/python -c "from _hermes_home import get_hermes_home; print(get_hermes_home())"`.
2. Verify the token path: `get_hermes_home() / "google_token.json"`.
3. If the token is not at that path, set `HERMES_HOME` explicitly: `export HERMES_HOME=/opt/data`.
4. If `hermes_constants` is importable, check that the active profile's `HERMES_HOME` matches (the poe profile's HERMES_HOME is `/opt/data`).

---

## Debugging path: `google_api.py` writes to the wrong Google Sheets spreadsheet

**Rule:** `google_api.py` uses a hardcoded spreadsheet ID (`1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0`) for the Revolut Research & Holdings sheet. The script may use a different sheet.

**How to apply:**

1. Check the spreadsheet ID in `google_api.py`: `SPREADSHEET_ID = "1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0"`.
2. Verify the spreadsheet exists and has tabs: `Watchlist`, `Research Log`, `Orders`.
3. If the script uses a different spreadsheet, update `SPREADSHEET_ID` in `google_api.py` (the copy at `/opt/data/scripts/productivity/google-workspace/scripts/` is writable; the original in `/opt/hermes/...` is root-owned).
4. The script `research_pass.py` also uses `SHEET_ID` (a different variable) for the spreadsheet ID.

---

## Debugging path: `research_pass.py` syntax error after edit

**Rule:** After editing `research_pass.py`, always run `py_compile` before running it. A syntax error will fail silently in cron.

**How to apply:**

1. Run `python3 -c "import py_compile; py_compile.compile('research_pass.py', doraise=True)"` to check syntax.
2. If the check passes, run the script with the Hermes venv Python.
3. If the script fails at runtime, check the traceback in the log file.

---

## Debugging path: `research_pass.py` import error after edit

**Rule:** After editing `research_pass.py` to use a different `google_api.py` path, the script may fail to import or find the `gapi` function.

**How to apply:**

1. Verify the `GAPI` path in `research_pass.py` points to the writable copy: `/opt/data/scripts/productivity/google-workspace/scripts/google_api.py`.
2. Verify the `gapi` function exists in `google_api.py` (it is defined at the bottom of the script).
3. Check the `IMPORT_ERROR` in the traceback.

---

## Debugging path: `research_pass.py` writes to the wrong spreadsheet

**Rule:** `research_pass.py` uses `SHEET_ID` (a variable) for the spreadsheet ID. It must match the spreadsheet ID in `google_api.py`.

**How to apply:**

1. Check `SHEET_ID` in `research_pass.py`.
2. Check `SPREADSHEET_ID` in `google_api.py`.
3. They must match: `1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0`.
4. If they differ, update the script's `SHEET_ID` to match.

---

## Debugging path: `google_api.py` batch_update not available

**Rule:** The `batch_update` command may not exist in `google_api.py` if it was not added yet.

**How to apply:**

1. Check `google_api.py` for `argparse.ArgumentParser` and `add_subparsers`.
2. Verify `sheets_batch_update` is defined.
3. If not, add it: parse the `--body` argument, send `spreadsheets().batchUpdate`, and return the response.

---

## Debugging path: Research Log append silently writes no rows

**Rule:** Pass `--values` to `google_api.py sheets append` as a JSON array of rows, not as an object containing a `values` key. The CLI wraps the array into the Sheets API request body itself; passing `{"values": [[...]]}` double-wraps the payload and can result in no written rows. Always check the subprocess return code instead of discarding stderr.

**How to apply:**

1. Use `json.dumps([row])` for a single append or `json.dumps(rows)` for a batch.
2. Treat a nonzero `google_api.py` return code as a write failure.
3. Read the exact Research Log range back after a test run.

## Debugging path: Research Log idempotency and localized dates

**Rule:** Google Sheets may return a datetime written as a localized display string such as `11/9/2026 10:55:11`, so idempotency checks must normalize displayed dates before comparing them with an ISO date such as `2026-11-09`.

**How to apply:**

1. Parse both ISO and common Sheets display formats.
2. Compare normalized `date().isoformat()` values.
3. Re-run the cron job and confirm the row count does not increase for the same ticker/day.

## Debugging path: Telegram summary is not delivered

**Rule:** Use the supported Hermes CLI form `hermes send --to telegram MESSAGE` (or `--file PATH`). Do not use `--channel` or `--text`; those flags are unsupported by current Hermes. Run the subprocess with `HERMES_HOME=/opt/data/profiles/poe` so it loads the active profile's Telegram credentials, and check its return code/stderr instead of suppressing errors.

**How to apply:**

1. Send the message as the positional argument or via `--file`.
2. Set the Telegram subprocess environment to the active profile home.
3. Log delivery success/failure.
4. Verify with `hermes send --to telegram ... --json`, which returns a `message_id` on success.

## Debugging path: LLM output is reported as unparseable

**Rule:** Run `hermes chat` in quiet single-query mode with the active profile (`--oneshot -Q --format text`, `HERMES_HOME=/opt/data/profiles/poe`). The normal CLI output includes banners, reasoning, and session metadata; the parser must extract the JSON object from that surrounding text. If parsing still fails, write the complete raw stdout/stderr into the HOLD rationale rather than replacing it with a generic message.

**How to apply:**

1. Use the active profile environment for the model subprocess.
2. Treat a nonzero model exit as raw diagnostic output, not an empty response.
3. Parse JSON embedded in the returned text.
4. Preserve the full raw output in the Research Log fallback row.

## Debugging path: ticker acronym collision produces a refusal

**Rule:** Search with both the ticker and canonical Watchlist name, then recover malformed/refusal output through a secondary model before writing a fallback row. If recovery fails, rerun the search with a more explicit company/fund query and retry the primary model.

**How to apply:**

1. Build the initial query from `ticker + Watchlist name + stock financial news`.
2. Ask the primary model to distinguish the named company/fund from unrelated acronyms.
3. If JSON parsing fails, send the raw output and digest to `reflection/beam-1.0-501b-a23b:free` with an explicit conversion prompt.
4. If that also fails, rerun the search with `company investor earnings price` disambiguation and ask the primary model again.
5. If all attempts fail, write every raw attempt to the Research Log rationale.

## Debugging path: `research_pass.py` writes the wrong value to the date column

**Rule:** The `to_serial` function must handle timezones correctly. The script stores `datetime.datetime.now(timezone.utc)` objects, so `to_serial` must convert to UTC before computing the serial.

**How to apply:**

1. Check `to_serial` handles the `tzinfo` attribute (it does — it converts to UTC).
2. Verify the serial for a known date matches Excel's expected value (e.g. 1900-01-01 → 1, 1900-03-01 → 61).
3. Verify the serial for the Research Log dates matches the values in the spreadsheet.

---

## Debugging path: `research_pass.py` batch append uses the wrong column range

**Rule:** The batch append writes to `A:G` (7 columns), but the log rows may have fewer keys.

**How to apply:**

1. Check the `log_rows` structure: `date`, `ticker`, `sentiment`, `rationale`, `sources` (5 keys).
2. The batch append writes `list(r.values())` → 5 values to `A:G` (columns A–E filled, F–G empty).
3. If the script needs to write more columns, update `log_rows` and the append block.

---

## Debugging path: `research_pass.py` overwrite issues

**Rule:** The script writes to the Research Log via both `write_log_row` and `sheets.append`. After the first run, there may be duplicate rows.

**How to apply:**

1. The script uses idempotency: `log_tickers_researched(today)` detects already-researched tickers by date+ticker and skips them.
2. The first run (21:16) wrote rows; the second run (21:24) was cut off.
3. The final run (21:32-21:36) wrote 5 rows to the Research Log.
4. The script uses `write_log_row` (per-row) and `sheets.append` (batch). The batch append is the authoritative write.

---

## Debugging path: `write_log_row` uses the wrong date format

**Rule:** The Research Log date column should contain serial numbers, not ISO strings.

**How to apply:**

1. Check `write_log_row` — it now converts `date` to a serial number via `to_serial()`.
2. Verify the function accepts `(date, ticker, sentiment, rationale, sources)` and converts the date.
3. Verify the function writes to columns A–E.

---

## Debugging path: `research_pass.py` doesn't set the date picker number format

**Rule:** Writing serial numbers is not enough; the number format must also be set.

**How to apply:**

1. Check the `batchUpdate` block in `research_pass.py` — it uses `repeatCell` with `numberFormat.type = "DATE_TIME"`.
2. Verify the `repeatCell` range covers the rows written (startRowIndex = 1, endRowIndex = 1 + number of rows).
3. Verify the format is `yyyy-mm-dd hh:mm:ss`.

---

## Debugging path: `research_pass.py` uses a root-owned google_api.py

**Rule:** The original `google_api.py` is at `/opt/hermes/skills/productivity/google-workspace/scripts/` and is root-owned. A patch attempt to it fails with "Write denied".

**How to apply:**

1. Copy the file to a writable location: `cp /opt/hermes/skills/productivity/google-workspace/scripts/google_api.py /opt/data/scripts/productivity/google-workspace/scripts/google_api.py`.
2. Patch the copy.
3. Update `research_pass.py` to use the copy path: `GAPI = "/opt/data/scripts/productivity/google-workspace/scripts/google_api.py"`.
4. Verify the copy is used in the subprocess (the script's `gapi` function uses `GAPI`).

---

## Debugging path: `research_pass.py` failed at 21:24

**Rule:** The 21:24 run was cut off mid-way through the `write_order_row` and `update_watchlist_last_researched` calls, leaving the script in a partially-completed state.

**How to apply:**

1. The cron worker resumed the script at 21:32 and completed it at 21:36.
2. The final run wrote 5 rows to the Research Log.
3. The job state was verified: `last_status: ok`, `last_run_at: 21:36:56`.

---

## Debugging path: `research_pass.py` job state verified

**Rule:** After running the script, verify the job state and the Research Log contents.

**How to apply:**

1. Check the job state: `cron.jobs.get_job(job_id)` → `last_status: ok`, `last_run_at: 21:36:56`.
2. Check the Research Log: `google_api.py sheets get "Research Log!A:G"`.
3. Verify the 5 active tickers (NVDA, AAPL, SPCX, VUAA, VWCE) are present.
4. Verify the date column values are serial numbers.

---

## Debugging path: `google_api.py` returns "Not authenticated"

**Rule:** The OAuth token was expired at the time of the initial `google_api.py sheets get` call. The token was refreshed before the script ran.

**How to apply:**

1. Check the token's expiry: `datetime.fromisoformat(expiry)` — the token was valid until 2026-11-07 23:04:09 UTC.
2. Refresh the token if expired: use the refresh flow.
3. Verify the token is written back to `google_token.json`.

---

## Debugging path: `research_pass.py` runs successfully

**Rule:** The final run at 21:32-21:36 completed successfully, writing 5 rows to the Research Log.

**How to apply:**

1. Verify the script runs without error: `run_one_job` returned `True`, exit code 0.
2. Verify the Research Log has the expected rows: NVDA (BUY), AAPL (HOLD), SPCX (BUY), VUAA (HOLD), VWCE (HOLD).
3. Verify the date column values are serial numbers.

---

## Debugging path: `research_pass.py` scripts directory

**Rule:** `research_pass.py` originally referenced `/opt/hermes/skills/productivity/google-workspace/scripts/google_api.py`, which is root-owned. The script now references the writable copy.

**How to apply:**

1. Verify `GAPI` in `research_pass.py` points to `/opt/data/scripts/productivity/google-workspace/scripts/google_api.py`.
2. Verify the copy has the `batch_update` command added.
3. Verify the copy has the `sheets_append` function with the `to_serial` conversion.

---

## Notes

- The `google_token.json` file contains credentials; its values are [REDACTED] in any documentation.
- The spreadsheet ID `1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0` is a data value, not a secret.
- The poke profile directory `/opt/data/profiles/poe` was changed from `0775` to `755` (owner `hermes`, group `hermes`) after the script was run.
