---

name: revolut-research
description: "Revolut Research & Holdings personal watchlist research/advisory/cron job: reads Google Sheet, researches tickers, writes BUY/SELL/HOLD to Research Log, appends orders to Orders tab. Read-only advisory; never touches Watchlist status checkboxes. 24-hour cron for personal, low-frequency investing (starting ~€20, scale €100+)."
category: research
version: 2.0.0
author: Hermes Agent + User
license: MIT
metadata:
  hermes:
    tags: [revolut, research, google-sheets, cron, advisory, personal-investing]
---

# Revolut Research & Holdings

Personal Revolut watchlist research/advisory/bookkeeping pipeline. The agent:
- Reads the Watchlist tab from a Google Sheet (`Revolut Research & Holdings`).
- Searches web for each ticker, extracts news, produces grounded BUY/SELL/HOLD reasoning with citations.
- Appends to the Research Log tab.
- Appends BUY/SELL order rows to the Orders tab (new tab in the same sheet).
- Runs on a 24-hour cron schedule.

This is a **read-only advisory pipeline**. No account access, no execution. All Revolut activity (trades) is manual by the user.

---

## Personal investing boundaries (always-on)

- **Not day trading**: The cron job runs every 24 hours for periodic research, not high-speed trading.
- **Not medium/long-term holding**: The focus is short-term (a few days/weeks) for personal testing; small starting balance (~€20), scalability to €100+.
- The Orders tab is meant for manual trade execution by the user — the script provides recommendations (`recommended_price`, `recommended_timestamp`) and the user fills executed fields.
- **Check both active watchlist tickers AND open BUY orders** (with `executed_amount` > 0) in the Orders tab for sell/hold evaluation.

---

## Hard Rules (always-on, apply to every run)

1. **NEVER touch the Watchlist `status` column.** That column is a user-managed checkbox (TRUE/FALSE). The agent reads it, respects it, and never modifies it. The user manages it manually; the script only reads it.
2. **Currency is always EUR.** The `Orders` tab has no currency column. Code must never consider any other currency.
3. **`rec_timestamp` semantics.** `rec_timestamp` = when the recommendation was made (recommendation time), **not** when the research was produced. Use current UTC datetime (ISO 8601).
4. **Executed fields are manual.** `executed_amount` and `executed_timestamp` are purely manual. The user fills them in when they act on a recommendation. When writing order rows, leave these fields empty.
5. **Idempotent re-runs.** The script is designed to be run repeatedly via cron without duplicating rows. `log_tickers_researched(today)` detects already-researched tickers by date+ticker and skips them. Use `RESET_LOG=1` to reset the Research Log when switching watchlist content.
6. **Read-only advisory design.** The Watchlist lives in the user's Google Sheet. The agent only reads public news and writes reasoning to the Research Log. The user remains the sole modifier and only source for account-specific tradeability.

---

## Procedure (standard research pass)

### Step 1 — Verify environment & sheet
- Ensure `$HERMES_HOME` points to the correct Hermes home (e.g., `/opt/data`).
- Verify the Google Sheet `Revolut Research & Holdings` (spreadsheet ID `1N8H0MXUrCSl2zDBArQNyFohjpCTQTqf-Mn0aZyB7MH0`) exists and has three tabs: `Watchlist`, `Research Log`, `Orders`.
- Verify auth token at `$HERMES_HOME/google_token.json` (scopes: `https://www.googleapis.com/auth/spreadsheets`).

### Step 2 — Check watchlist status (read-only)
- Read the `Watchlist` tab. For each row, check column `E` (`status`):
  - Accepted values: `TRUE`, `1`, `active`, `yes` (case-insensitive).
  - Skip rows where `status` is `FALSE`, empty, or any other value.
  - **NEVER modify the `status` column.** It is user-managed.

### Step 2b — Date column format (date picker)
- The date picker in Google Sheets is **format-driven, not value-type-driven**.
  - String cells never show a picker.
  - Numeric cells show a picker only when the cell's number format is a date/datetime format.
- **Write date values as ISO 8601 datetime strings** (e.g., `2026-11-08 0:00:00`), NOT Excel serial numbers.
  - Raw serial numbers (e.g., `46333.9475806932`) are NOT recognized by Google Sheets as valid datetime cells.
- After appending rows, send `sheets.batchUpdate` with a `repeatCell` request that sets
  `numberFormat.type = "DATE_TIME"` and `numberFormat.format = "M/D/YYYY H:MM:SS"`
  (e.g., `11/8/2026 0:00:00`) on the date column for the rows just written.
- The display format MUST be `M/D/YYYY H:MM:SS` (NOT `yyyy-mm-dd hh:mm:ss`).
- The number format (M/D/YYYY H:MM:SS, DATE_TIME type) MUST be applied to date columns after writing; both the value and the format are required for the picker to work.

### Step 3 — For each active ticker (status=TRUE):
a. **Search** web results for the ticker (use `web_search_tool`).
b. **Extract** the top article body (use `web_extract_tool`, max 20s, skip market-data/quote pages).
c. **Build digest** from search results + top extraction.
d. **Ask model** for `BUY | SELL | HOLD` + rationale + sources + `recommended_price` (EUR).
e. **Parse model output** (JSON object; iterative extraction). If parsing fails, **write a HOLD row** with the raw model output as the rationale (truncated to 500 chars), so every active ticker reports something in the Research Log — never skip the row.
f. **Write log row** to `Research Log` (columns: `date`, `ticker`, `sentiment`, `rationale`, `sources`).
g. **Write order row** to `Orders` if sentiment is BUY or SELL (columns: `ticker`, `side`, `recommended_price`, `recommended_timestamp`, `executed_amount`, `executed_timestamp`, `executed_price`, `commission`, `value`, `position`, `order_id`).
   - The `recommended_price` is the current price of the stock/ETF in EUR (output by the model).
   - The `executed_amount`, `executed_timestamp`, `executed_price`, `commission`, and `value` columns are left empty for manual entry, except `value` is auto-calculated as `executed_amount * executed_price` when both are present.
   - Each new order gets a unique `position` (uuid4, groups BUY/SELL) and `order_id` (uuid4).
h. **Update `last_researched`** (Watchlist column F) with current UTC datetime.

### Step 4 — Write rows to the Research Log
- **Per-row immediate append**: For each ticker, write the log row immediately to `Research Log!A:E` using `gapi(["sheets", "append", ...])` with `--values` as a JSON array of a single row (e.g. `json.dumps([[date, ticker, sentiment, rationale, sources]])`). This ensures partial results survive a timeout mid-run.
- **Batch append**: After all tickers, append any remaining rows in one batch call.
- **Note**: `google_api.py sheets append` expects `--values` as a JSON array of rows (a 2D array), NOT a dict containing a `values` key. Passing `{"values": [[...]]}` double-wraps and can result in no rows written.

### Step 5 — Telegram summary
- At the end of the run, send a Telegram summary to the home channel (9238079416) with all BUY/SELL recommendations: ticker, sentiment, timestamp, and one-line reason.
- If no BUY/SELL recommendations were generated, send: "No BUY or SELL recommendations were generated today."
- If the run timed out mid-way, resume the script from the same point in the next run (it is idempotent — `log_tickers_researched(today)` detects already-researched tickers by date+ticker and skips them).

### Step 6 — Positions pivot table
- The Positions tab is a pivot table showing `SELL value - BUY value` per position.
- It uses a helper column (L) in the Orders tab with formula `=I{row}` for SELL orders and `=-I{row}` for BUY orders.
- The pivot table references column 11 (L) from the Orders tab, grouped by column 9 (`position`).

### Step 7 — Batch-append all new Research Log rows
- After all tickers, append any remaining rows in a single `sheets.append` call to minimize API calls.

## Personal investing boundaries (always-on)

- **Not day trading**: The cron job runs every 12 hours for periodic research, not high-speed trading.
- **Not medium/long-term holding**: The focus is short-term (a few days/weeks) for personal testing; small starting balance (€20), scalability to €100+.
- The Orders tab is meant for manual trade execution by the user — the script provides recommendations (recommended_price, timestamp) and the user fills executed fields.

---

## Google Sheets date picker

The picker is **format-driven, not value-type-driven**:

- **Strings** → no picker, rendered as plain text.
- **Real date values** (serial numbers or epoch timestamps) → the cell value is a number; the picker appears when the **number format** is a date/datetime format.

To unlock the picker on a column:
1. Write date values as ISO 8601 datetime strings (e.g., `2026-11-08 0:00:00`), NOT raw Excel serials.
2. Send `sheets.batchUpdate` with a `repeatCell` request that sets:
   - `numberFormat.type = "DATE_TIME"`
   - `numberFormat.format = "M/D/YYYY H:MM:SS"`
   - applied to the date column for the rows just written (via `repeatCell` + `userEnteredFormat.numberFormat`)

Both the correct value (ISO string) AND the correct number format (DATE_TIME) are required for the date picker to work. Raw Excel serials (e.g., `46333.9475806932`) are NOT recognized by Google Sheets as valid datetime cells.

---

## Pitfalls & Why

| Pitfall | Why it happens | How to avoid |
|---|---|---|
| `gapi` subprocess resolves to wrong Python interpreter | Cron worker PATH places a store venv before `/opt/hermes/.venv/bin`, so bare `python` resolves to a venv lacking Google packages. | Always use absolute venv interpreter in subprocess commands, e.g. `"/opt/hermes/.venv/bin/python /opt/hermes/skills/productivity/google-workspace/scripts/google_api.py"`. |
| `log_tickers_researched` never triggers idempotency | `spreadsheets().get(range=...)` returns a keyed dict, not a `values` array. | Use `_svc.spreadsheets().values().get(spreadsheetId, range="Research Log!A:G")` and compare `_row[0] == today`. |
| Script runs but produces no rows | The model output cannot be parsed as JSON. | The script **skips writing to the log** and prints a skip message when parsing fails. |
| 12-ticker run hangs on one ticker | `build_digest` calls `web_extract_tool` on a market-data page (marketwatch.com) that extracts poorly; `ask_model` has no timeout. | Bound `run()` with `timeout=120`; bound `build_digest` extraction with 20s; skip market-data pages; set `ask_model` timeout to 90s. |
| Order rows not written (no BUY/SELL) | All researched tickers got `HOLD` sentiment, so `write_order_row` was never called. | Verify model output includes `recommended_price` and sentiment is BUY/SELL for order rows to be written. |

### Orders tab schema (current)
The Orders tab has 10 columns:
`ticker`, `side`, `recommended_price`, `recommended_timestamp`, `executed_amount`, `executed_timestamp`, `executed_price`, `commission`, `value`, `position`, `order_id`
- `recommended_price` (EUR, from model)
- `executed_amount`, `executed_timestamp`, `executed_price`, `commission`, `value` — manual entry; `value` = `executed_amount * executed_price` when both present
- `position` (uuid4), `order_id` (uuid4) — generated per order

### Positions tab (net gain/loss pivot)
- The Positions tab is a pivot table showing `SELL value - BUY value` per position.
- It uses a helper column (column L) in the Orders tab with formula `=I{row}` for SELL orders and `=-I{row}` for BUY orders.
- The pivot table references column 11 (L) from the Orders tab, grouped by column 9 (`position`).

---

## Script usage

```bash
# Run a research pass (resets the Research Log first if RESET_LOG=1)
cd /opt/data/scripts
export HERMES_HOME=/opt/data
RESET_LOG=1 python research_pass.py > /tmp/research_pass.log 2>&1
```

## Cron

Cron job ID: `1333b450797a` (schedule `0 */12 * * *`, every 12 hours).

---

## Security boundary

- No API keys/tokens/passwords/secrets/credentials in summary; credentials present in source but values are not preserved. Anything that could identify real credentials must be written as `[REDACTED]`.

---

## References

- `references/pitfalls.md` — debugging paths and tool-usage patterns.
- `references/commands.md` — exact commands for common operations.
