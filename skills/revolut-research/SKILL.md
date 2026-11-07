---
name: revolut-research
description: "Revolut Research & Holdings personal watchlist research/advisory/cron job: reads Google Sheet, researches tickers, writes BUY/SELL/HOLD to Research Log, appends orders to Orders tab. Read-only advisory; never touches Watchlist status checkboxes."
category: research
version: 1.0.0
author: Hermes Agent + User
license: MIT
metadata:
  hermes:
    tags: [revolut, research, google-sheets, cron, advisory]
---

# Revolut Research & Holdings

Personal Revolut watchlist research/advisory/bookkeeping pipeline. The agent:
- Reads the Watchlist tab from a Google Sheet (`Revolut Research & Holdings`).
- Searches web for each ticker, extracts news, produces grounded BUY/SELL/HOLD reasoning with citations.
- Appends to the Research Log tab.
- Appends BUY/SELL order rows to the Orders tab (new tab in the same sheet).
- Runs on a 12-hour cron schedule.

This is a **read-only advisory pipeline**. No account access, no execution. All Revolut activity (trades) is manual by the user.

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
  -Accepted values: `TRUE`, `1`, `active`, `yes` (case-insensitive).
  - Skip rows where `status` is `FALSE`, empty, or any other value.
  - **NEVER modify the `status` column.** It is user-managed.

### Step 3 — For each active ticker (status=TRUE):
a. **Search** web results for the ticker (use `web_search_tool`).
b. **Extract** the top article body (use `web_extract_tool`, max 20s, skip market-data/quote pages).
c. **Build digest** from search results + top extraction.
d. **Ask model** for `BUY | SELL | HOLD` + rationale + sources + `recommended_amount` (EUR).
e. **Parse model output** (JSON object; iterative extraction).
f. **Write log row** to `Research Log` (columns: `date`, `ticker`, `sentiment`, `rationale`, `sources`).
g. **Write order row** to `Orders` if sentiment is BUY or SELL (columns: `ticker`, `side`, `recommended_amount`, `recommended_timestamp`; `executed_amount` and `executed_timestamp` left empty).
h. **Update `last_researched`** (Watchlist column F) with current UTC datetime.

### Step 4 — Batch-append all new Research Log rows
- Collect all new log rows, then append in a single `sheets.append` call to minimize API calls.

### Step 5 — Finalize
- Print summary: rows written, tickers researched, order rows written.
- If `RESET_LOG=1` was set, reset the Research Log first (delete existing rows below the header).

---

## Pitfalls & Why

| Pitfall | Why it happens | How to avoid |
|---|---|---|
| `gapi` subprocess resolves to wrong Python interpreter | Cron worker PATH places a store venv before `/opt/hermes/.venv/bin`, so bare `python` resolves to a venv lacking Google packages. | Always use absolute venv interpreter in subprocess commands, e.g. `"/opt/hermes/.venv/bin/python /opt/hermes/skills/productivity/google-workspace/scripts/google_api.py"`. |
| `log_tickers_researched` never triggers idempotency | `spreadsheets().get(range=...)` returns a keyed dict, not a `values` array. The check `spreadsheets().get(range=...)` returns a keyed response → always empty. | Use `_svc.spreadsheets().values().get(spreadsheetId, range="Research Log!A:G")` and compare `_row[0] == today`. |
| Script runs but produces no rows | `read_watchlist_rows()` returns empty because the script's interpreter is the system Python (no `httpx`/`google-api-client`). | Verify the interpreter has `google-api-client` and `httpx`. Use the Hermes venv Python at `/opt/hermes/.venv/bin/python`. |
| 12-ticker run hangs on one ticker | `build_digest` calls `web_extract_tool` on a market-data page (marketwatch.com) that extracts poorly; `ask_model` has no timeout. | Bound `run()` with `timeout=120`; bound `build_digest` extraction with 20s; skip market-data pages; set `ask_model` timeout to 90s. |
| Order rows not written (no BUY/SELL) | All researched tickers got `HOLD` sentiment, so `write_order_row` was never called. | Verify model output includes `recommended_amount` and sentiment is BUY/SELL for order rows to be written. |
| Orders tab appears empty after run | The new Orders tab was created with a different sheetId, but the script uses the tab name (`"Orders"`) for appending. Verify the tab name matches exactly. | The script appends using the tab name `ORDERS_TAB = "Orders"`. Ensure the tab still exists in the sheet. |

---

## Reference files

- `references/pitfalls.md` — detailed debugging paths and tool-usage patterns observed during this project.
- `references/commands.md` — exact commands for common operations.

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
