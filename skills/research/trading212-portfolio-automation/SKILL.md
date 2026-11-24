---
name: trading212-portfolio-automation
description: "Use for guarded Trading 212 research and orders."
version: 1.0.0
author: Hermes Agent + User
license: MIT
metadata:
  hermes:
    tags: [trading212, investing, portfolio, orders, cron, risk-controls]
    category: research
---

# Trading 212 Portfolio Automation

Use this skill for Trading 212 account research, short-term stock/ETF trading, take-profit order placement, and recurring monitoring. It is tailored to the user's preference for concise, risk-controlled trades rather than leverage or unsupported derivatives.

## When to Use

Load this skill when the user asks to inspect a Trading 212 account, research candidate trades, place or manage orders, construct a portfolio, or schedule recurring portfolio monitoring.

## Standing rules

- Treat "maximize profit" as an optimization goal, never a guarantee; state material uncertainty plainly.
- Read the account environment label at runtime from `ENVIRONMENT` under `mcp_servers.trading212.env` in `config.yaml`; state that exact value (e.g. `demo` or `live`) — never hardcode the label here. The account is not fixed to DEMO; if the user switches the config to live, report LIVE.
- Never use leverage, inverse products, CFDs, short positions, or options-income products unless the user explicitly changes this standing policy.
- Never duplicate an existing position, pending order, protective stop, or profit-taking order. Treat matching instrument/side exposure as a hard no-new-order gate unless the user explicitly changes this policy.
- Distinguish Trading 212 order lifecycle status from run provenance: API `NEW` means an unfilled order, not an order created by the current run. Render existing unfilled orders as `PENDING` in the **Open orders** section, and reserve New orders this run for orders actually placed during this execution.
- **Short-term bracket-exit mode is active for this cron** — allow both stocks and ETFs. Every filled buy receives one full-position GTC take-profit sell limit and one full-position GTC stop-market sell at the configured percentages from the actual average fill, unless protective sell orders already exist.
- **Distribution policy comes from the instrument name, never the ticker suffix.** Trading 212 suffixes encode the listing venue (`d`=Xetra, `a`=Amsterdam, `l`=London, `s`=Swiss, `m`=Milan, ...), NOT Acc/Dist: e.g. `VWCEd_EQ` and `CEBZd_EQ` are accumulating, `VUSAa_EQ` and `VWRLa_EQ` are distributing. The authoritative markers are `(Dist)` / `(Acc)` in the catalogue `name` field.
- **Cash-withdrawal objective: prefer distributing ETF share classes.** When catalogue matches are ambiguous, resolve deterministically: account-currency settlement first, then `(Dist)` share class, then exact ISIN/ticker; same-ISIN listings on different venues are the same share class and tie-break by ticker. A uniquely matched accumulating ETF is swapped to its distributing sibling (same fund name, same currency, single ISIN) when one exists. Never guess an identity outside the verified catalogue.
- **Trading 212 has no native OCO/bracket endpoint in the equity API.** The two exits are independent orders. Reconcile every run, cancel orphaned sibling exits after one fills, verify cancellation, and stop on uncertain cancellation state.
- **Non-JSON MCP write responses retry with the same contract as 429s.** Trading 212's free tier also returns `non-JSON data` for ordinary tool calls (rate limit, gateway blip, upstream format change), e.g. `place_limit_order` returned `HTTP/1.1 400 Bad Request` with an empty body. Bounded retry (4 attempts, 2s → 4s → 8s, cap 30s) applies to these too, and any 4xx that is purely a payload/broker-rule validation (e.g. `price too far`, invalid quantity, unknown ticker) is non-retryable — but even those must not abort the whole run: record the order as `REJECTED_BY_BROKER` / `ERROR` with ticker, quantity, limit, and the broker response, and keep executing the remaining orders. A single failed placement must never turn the whole execution into a failed run; the run reports, then moves on.
- **Per-order failure handling.** When a placement write or its readback exhausts retries, append `{"ticker": ..., "status": "REJECTED_BY_BROKER"|... , "reason": ...}` to this run's results instead of raising. The rendered report lists these rows under **Orders this run** and continues with the remaining orders.
- **Report tickers are suffix-stripped** — display `VUAA`, not `VUAAm_EQ` — via `_strip_ticker_suffix` in the report template; underlying instrument identity (ISIN/price/quantity) preserves the full Ticker.
- **Pre-trade lot gate before placement:** before every buy order reaches `place_limit_order`, compute the instrument's minimum tradable lot from its account catalogue record (`minTradeQuantity` / `min_trade_quantity`) and deterministically reject anything below it as a `REJECTED_BY_BROKER` row — no broker call for that order:

  ```text
  min_lot = instrument_min_trade_quantity(catalog_records, order.ticker)
  if min_lot is not None and order.quantity < min_lot:
      results.append({ticker, status: "REJECTED_BY_BROKER",
                      reason: f"below minimum tradable lot ({min_lot} shares)",
                      quantity, limit_price})
      continue   # never sends that order to the broker
  ```

  A catalogue entry with `minTradeQuantity` unset is *unknown*, not *zero*: never hard-block on an absent minimum, log the miss, and let the broker's own rule layer be the fallback. This gate is why an order below the account tradable minimum (IWLEq_EQ ≈ 0.09900500 shares ≈ €1.00) was refused before it ever reached the broker. The gate lives in `scripts/t212_portfolio_automation.py`, `execute_orders`; report carry-over follows `references/broker-rejection-flow.md`.

- **Deterministic Telegram delivery:** send the renderer's stdout verbatim as the only message content. Do not add a preamble, code fence, verification footer, or explanatory wrapper, because Telegram formatting can make a correct template appear to differ.
- **Research-quality gate:** Before the selector sees web-search results or extracted content, filter out known junk pages (interstitials such as Relevance Inspector and Forwarding/Connecting markers, short/error-page fragments, rows whose title is the search query itself) and deduplicate by URL + normalized content hash. Require real readable content over 200 characters per item. Do **not** rescan junk/interstitial pages — they do not become readable on re-scrape, so only transient 429/408/425/5xx/timeout/network failures are retried. A low-signal study renders with a stated status (e.g. `Extraction: succeeded (low signal: N quality sources)`), and the reason is written to the report — never silently converted into an empty run.
- **Extraction target rotation:** research extraction targets rotate toward structured, readable sources (fund factsheets, comparison pages, ETF explorers) over generic pages, up to 6 non-junk URLs quality-ranked, so the selector receives evidence rather than decision-page noise.
- **Verify the research gate end to end before declaring it fixed:** run the quality tests with `/opt/hermes/.venv/bin/python` and the profile user-site `PYTHONPATH`, use `unittest discover` rather than executing function-style test files directly, run the live research command, and then invoke the cron wrapper once. Confirm the research JSON has usable sources and the cron log has no placement, rejection, extraction, selector, or runner errors; a successful compile alone is insufficient.

The research-quality gate lives in `references/research-quality-gate.md` (junk-marker table, retry boundary, status wording, content-length verification).
- **Market-hours facts (EUR account):** Xetra, Amsterdam and all EUR listings trade Mon–Fri 08:00–16:30 UTC. This account executes only in EUR, so US extended hours do not apply. TP/SL exits remain on the book overnight and resume at the next open; no fills can occur in closed-market hours.
- **Silent cron delivery:** for a `no_agent` script job, print an empty stdout on a successful run with no order placement, fill, or research-phase issue; the scheduler then sends no Telegram message. Let nonzero exits and timeouts carry operational error alerts, and emit the full rendered report only for a placement/fill or a detected research issue.
- **Report one-line** — render Current orders as compact mobile-readable one-line records in the form `TICKER: BUY QTY @ PRICE (ID: <order_id> Since: <timestamp>)`. Do not use a wide table, status prefix, bullet card, `#` marker, or currency symbol in this line; preserve the full ticker and exact API values. Report TP/SL orders as protective exits, not as new buys.
- Combine candle and extraction health into one Research section. On success render only `- Candles: resolved for N tickers` and `- Extraction: succeeded`; include per-symbol candle errors or extraction diagnostics only when an issue exists.
  window (the current EUR-settled setup uses `*/30 8-18 * * 1-5` in UTC). Do not call this true day trading unless there is also a same-session close rule or real-time monitoring. See `references/trading-hours-and-market-cycles.md` for venue hours, extended-hours limits, and overnight GTC behavior.
- In short-term bracket-exit mode, stocks and ETFs are both eligible, but only EUR-settled instruments are allowed; preserve staged sizing and reject leverage, inverse products, CFDs, shorts, and options.
- Preserve a cash reserve and use staged entries; do not deploy the full balance on the first run.
- **Default order sizing caps each LLM-provided `allocation_pct` at 0.20 and promotes small proposals to at least €1.00 when reserved cash covers it; allocations at or below the cap are preserved as provided. Take-profit defaults to 0.03 and stop-loss defaults to 0.015; both are configurable at runtime.
- Recurring automation must discover candidates from current account state and current research; do not hardcode specific tickers, funds, exchanges, or fixed allocations into the reusable skill.
- This Trading 212 cron sends its required Telegram summary but does not write to Google Sheets; another job owns that log. Do not access OAuth tokens or bootstrap optional integrations during a run.
- Keep every completion report to the minimum necessary — account state, orders/positions, verification result, and what remains pending — without recap prose. Report concisely: short bullets, state results plainly, and answer directly when asked. A one-word confirmation (e.g. 'OK!') is acceptable for yes/no or state questions.
- **Credential-handling rule:** never preserve API keys, tokens, passwords, secrets, connection strings, or credentials in any summary, report, or log output — replace with [REDACTED]. Applies to Trading 212 API keys, MCP auth, Telegram bot tokens, and any other credentials.
- Treat market-data provider selection as unverified until a live request returns parseable OHLCV rows. A fallback provider proves only that the fallback worked; report the primary provider as unavailable rather than implying it succeeded.
- Candle-provider errors are per-symbol failures: record the symbol and error, continue with the remaining instruments, and use the fallback provider where configured. Retry only transient 429/408/425/5xx/network failures with bounded exponential backoff; do not retry permanent 4xx errors.
- Research extraction uses the same retry contract: per-URL transient failures (429/408/425/5xx/timeout/network) retry up to 3 times with 2s→4s→8s backoff (cap 30s); successful URLs are never re-scraped; permanent 4xx and empty-content pages are not retried. Failure reasons must be preserved in the extraction status so the run report says why.
- The candle set must always be the union of open positions, pending orders, and research-selected candidates. Never set candles to `None` merely because the selector produced no new order candidates; an empty new-order plan does not mean the account source is empty.
- Preserve the full Trading 212 identity for every candle request: exact full ticker, ISIN, and currency. Trading 212 list/order records may omit exchange, so let the provider resolver fill a verified venue mapping; do not reject an otherwise complete account instrument only because the exchange field is absent.
- Validate provider capability with the exact historical `time_series` request, not symbol discovery alone: a symbol can appear in the catalog while historical data is unavailable for the account's plan or market coverage. Report key authentication, symbol resolution, historical entitlement/coverage, rate limiting, and fallback success as separate statuses; never label a configured key missing when the historical endpoint returns 404.
- Keep reusable profile data under `$HERMES_HOME/cache/`; use `$HERMES_HOME/cache/scratch/` only for per-run inputs and temporary files. Do not place candle caches in a global root or inside the skill directory.
- Resolve every runner, config, cache, MCP, and LLM path from `$HERMES_HOME`; never embed a profile's absolute name in reusable scripts or cron wrappers, because profile renames otherwise leave jobs pointing at the old path.
- For recurring cron runs, enable scheduler continuity and read only the previous run's `Next actions`/`Next steps` section as provisional context; re-verify every carried-forward action against current account state before acting.
- When implementing recurring automation as a script, keep the LLM limited to research/candidate selection; Python must own state reads, identity validation, sizing, duplicate gates, writes, readbacks, rendering, and delivery.
- Make dry-run the default for new or unapproved runners; once the user authorizes scheduled execution, the cron wrapper must pass `--execute`. Treat the configured `ENVIRONMENT` as the authoritative demo/live target, not as a substitute for the execution flag; require a separate explicit live-environment approval gate.
- **Selector constraints should be calibrated to the model, not assumed strict.** The default selector is conservative and may reject candidates that are technically valid. After an empty `{"candidates": []}` result, relax constraints in this order: (1) allocation upper bound `0 < x <= 1`; (2) accept ISIN-exact or partial ticker match; (3) widen context only to verified working bounds. Re-validate every candidate through the cached Trading 212 catalogue after relaxation — never accept a candidate the model fabricates.
- When using scripted candidate selection, maintain a profile-owned Trading 212 instrument catalogue cache keyed by environment (for example `$HERMES_HOME/cache/trading212/instruments-demo.json`); store `fetched_at`, environment, count, and raw records, write updates atomically, refresh it about every 24 hours, and use its exact ticker/ISIN records for the current EUR ETF universe. The catalogue cache (e.g. $HERMES_HOME/cache/trading212/instruments-live.json) holds fetched_at, environment, count and raw records; it refreshes weekly (7-day TTL) on a live fetch and is never used for new orders once the live data is older. Force-refresh the catalogue after an unknown ticker or broker rejection. Never let the model invent identifiers from web research or memory.
- **Choose and verify the selector model through cron configuration, not source edits.** For this no-agent script job, set the job pin with `hermes cron edit <job_id> --model <model> --provider <provider>`; the cron wrapper must pass those fields to `t212_llm.py`. Clear both fields to follow the profile default. Keep the adapter's `--model`/`--provider` options generic and never hardcode a model in the script. Log the effective model/provider in the per-run log before execution so a Desktop-triggered run can be verified, not merely inferred from dashboard state.
- **Keep the selector call bounded and tool-free.** Send one compact prompt (account state + research + candle status) and require JSON-only output. Keep account state, research, and ticker context within verified model limits; use the job's configured model/provider explicitly. On timeout, non-zero exit, or malformed output, fail the run with a non-zero status and include the raw selector output or timeout diagnostics (tail-truncated); never convert an unavailable selector into a silent empty candidate list or a false successful report.

- **LLM selector retries with classified failures.** The free-tier LLM selector (Nous API via `hermes chat`) can be slow or fail to start. Retry transient timeouts and gateway/network failures with bounded backoff: 4 attempts, delays 5s → 10s → 20s (capped at 30s), printing each retry to stderr. On the final attempt, fail nonzero with a classified diagnostic; never convert a hard gateway, permission, nonzero-exit, or malformed-JSON error into a generic timeout or a normal empty-candidate report.

- **Report LLM selector failure explicitly.** When the selector call times out, exits non-zero, or returns malformed JSON, do not fall back to empty candidates or render a normal completion report. Fail the script non-zero and include a bounded tail of the raw selector output or timeout diagnostics in the cron failure report, so a selector failure cannot be mistaken for a valid no-order run. A normal empty candidate list is allowed only when the selector returned valid JSON `{"candidates": []}`.

```text
**Research**
- Candles: resolved for N tickers
- Extraction: succeeded

**LLM selector warning**
- Warning: the LLM selector timed out after 600 seconds; falling back to empty candidates.
- This means no new orders could be generated this run. Please re-run a future cycle.

**Sources**
```

Only include this section when `llm_timed_out` is true — do not add it for normal empty-candidate results. Only expand context after the model returns `{"candidates": []}` with no timeout.
- **The Trading 212 free API rate-limits aggressively (roughly 15–30 requests per minute).** The free-tier Pro account with pending orders generates ~21 sequential MCP calls per run (5 in account collection + 7 per order × 3 orders). When a call returns HTTP 429, do not abort: retry with bounded exponential backoff (2s → 4s → 8s → cap 30s), printing each retry to stderr. Implement this in the MCP wrapper so the retry policy is shared across the whole pipeline, not duplicated per call site. The pipeline must survive three consecutive 429s before giving up.<br>
- **Account state is fetched once for planning and reconciled once after buys.** `collect_state` supplies the initial plan; do not re-fetch account data inside each order loop. After buy placement, perform one fresh collection before planning take-profit sells so same-run fills and changed reservations are visible.

## Hermes config and toolchain setup (one-time)

- Set the web search/extract backend explicitly (default `auto` → `openai-native` fails on client-side search). `config.yaml` per-provider timeouts must be raised for the slow free-tier models:

```bash
hermes config set web_extract.provider firecrawl
hermes config set providers.nous.request_timeout_seconds 300
hermes config set providers.nous.stale_timeout_seconds 900
```

- `firecrawl` package lives in the profile's user site-packages (`$HERMES_HOME/home/.local/lib/python3.14/site-packages`) but is not visible to the Hermes venv by default. When running research/LLM commands, export `PYTHONPATH=$HERMES_HOME/home/.local/lib/python3.14/site-packages`. The `hermes chat` adapter (`t212_llm.py`) must run from the profile directory itself: it sets `HERMES_HOME`, `HOME`, and `PATH` explicitly, and its `subprocess.run` passes `--query-file - --oneshot -Q --format text --max-turns 10` so the bounded model returns JSON-only output. If the adapter's CWD is not the profile directory, `hermes chat` fails to resolve the skills/gateway; run from the profile root.

## Credential placement for the Trading 212 MCP server

The `trading212-mcp-server` loads `.env` with python-dotenv's `find_dotenv()`. With the
default `usecwd=False`, the search starts from the calling module's directory and walks
up to the filesystem root, returning the FIRST `.env` it meets.

For this profile that resolves to `$HERMES_HOME/.env` — the profile's own `.env`, not a
guessed absolute path such as `/opt/data/.env`. Place `TRADING212_API_KEY` and
`TRADING212_API_SECRET` in `$HERMES_HOME/.env`.

Verify the resolved file before placing secrets:

```bash
cd "$HERMES_HOME/.t212venv/lib/python3.14/site-packages/trading212_mcp_server"
"$HERMES_HOME/.t212venv/bin/python" -c "import dotenv; print(dotenv.find_dotenv() or 'NOT FOUND')"
```

Advance only when the probe prints a path ending in `.env` whose key/secret lines are
populated and parseable.

## Pipeline health checks

- Before running the full pipeline, verify the MCP server entrypoint is intact in the MCP server's venv (`$HERMES_HOME/.t212venv`):
  - Confirm `$HERMES_HOME/.t212venv/bin/trading212-mcp-server` exists and is executable, and that the venv can import the server package (`$HERMES_HOME/.t212venv/bin/python -c "import trading212_mcp_server"`).
  - Confirm `pydantic_core` C extension imports in the venv: `import pydantic_core`. If it fails with "No module named 'pydantic_core._pydantic_core'", the `.so` was lost during a prior reinstall. Reinstall with `python -m ensurepip --default-pip` then `pip install --force-reinstall pydantic_core==2.50.4` inside the venv and re-check by importing, not just by file presence. Also verify `pydantic` is consistent with `pydantic_core==2.50.4`.

### Diagnosing a failing cron run

When a recurring run exits nonzero, diagnose in phase order and stop at the first
fixable failure; do not jump ahead to later phases.

1. **MCP entrypoint** — confirm
   `$HERMES_HOME/.t212venv/bin/trading212-mcp-server` exists and is executable, and the
   venv imports the server package:
   `"$HERMES_HOME/.t212venv/bin/python" -c "import trading212_mcp_server"`.
   If the binary or import is missing, restore the venv from the cached trading212-mcp-server
   package before anything else.
2. **Credential resolution** — confirm `find_dotenv()` from the MCP package directory
   resolves to `$HERMES_HOME/.env`, and that the key/secret lines are present and
   parseable (see the credential-placement probe above). Missing or wrongly placed
   credentials fail at the MCP-connect phase — before any account call.
3. **Account collection** — read the run log for `fetch_account_*`, order, and position
   errors: HTTP 4xx (bad or placeholder credentials, 401/403), 429 (rate limit), or
   non-JSON (invalid payload). Fix only the mapped phase before re-running.
4. **Candles, research, selector** — then address each remaining error in order, because
   a credential failure always precedes candle, extraction, and selector diagnostics.
   Do not chase those while MCP calls are still failing.

## Procedure

0. **Validate profile portability before execution.** Confirm `HERMES_HOME` is the intended profile, audit executable source and launcher paths for stale profile names, verify the MCP launcher interpreter and `pydantic_core` import, and run a read-only MCP collection before enabling `--execute`. For a manually triggered live cron-wrapper run, invoke it through Python from the profile root (`T212_ALLOW_LIVE=1 python scripts/t212_portfolio_automation_cron.py`) rather than relying on the wrapper's executable bit; verify the live gate is explicitly enabled before allowing writes.
1. **Load metadata and account context.** Load the environment-keyed instrument catalogue from the profile cache once per run; refresh when older than the weekly TTL (7 days); fall back only to a bounded-age stale copy (hard max 7 days) for research only - never place orders from a catalogue older than the fresh fetch. Then fetch account info, cash, portfolio summary, all open positions, all pending orders, and recent activity. Record base currency, available cash, invested value, position count, and existing exposure. **Account state and catalogue are fetched once at the start and cached** — never issue repeated per-candidate metadata lookups or re-fetch account state inside order loops.
2. **Research current conditions.** Run the deterministic research command (web_search + web_extract) to gather current conditions and candidate tickers. Research supplies evidence; it does not choose tickers.
3. **Merge candidate tickers from 2 sources.** Source 1: existing open positions and pending orders (guaranteed tradeable). Source 2: research candidates from news/trends. Resolve exact trading instruments from Trading 212 metadata.
4. **Resolve candles.** Build the union of all open-position tickers, all pending-order tickers, and research-selected tickers; resolve missing Trading 212 metadata before collection; then invoke the candle collector once for the complete union. Record per-symbol provider, bar count, latest date, and error. A run with no new orders must still report candles for the account-source tickers.
5. **Bounded LLM selector call.** Resolve the selector model/provider from the cron job configuration, send one compact tool-free prompt (account state + research + candle status), and require JSON-only output. Accept an explicit empty `{"candidates": []}` result and relax constraints in order (1) allocation_pct upper bound `0 < x <= 1`; (2) ISIN-exact OR partial ticker match; (3) widen context only to verified working bounds. Treat timeout, non-zero exit, or malformed output as a failed run and preserve the raw selector output tail in diagnostics.
6. **Order planning.** Build the order plan from new candidates only (exclude already-positioned/pending tickers). Validate sizes against cached cash and check duplicates. Hard-gate each candidate against the account instrument catalogue before sizing (see `references/order-planning-gate.md`): exactly one tradable record must match — exact ticker OR exact ISIN, type ETF/STOCK, EUR settlement. Zero matches, ambiguous duplicates, or a non-ETF/STOCK record are deterministic rejections at this point (`<ticker>: <reason>`), never broker calls; on an unknown ticker or a broker rejection, re-load (force-refresh) the catalogue and re-plan instead of retrying the same sized order.
7. **Order execution.** Reconcile cash, positions, and pending orders immediately before writes. For each new BUY, call `place_limit_order` and `fetch_order`; do not re-fetch account state inside the order loop. After all buys, collect state once, cancel orphaned sibling exits, then build TP/SL exits from actual average fills and existing SELL orders. Place one full-position GTC SELL limit plus one full-position GTC SELL stop per eligible position and read back every write. If the second bracket leg fails, cancel the first before failing the run.
8. **Render and deliver.** Render the standardized report template (see Template format section below). Include BUY and SELL orders separately. No preamble, no Telegram snapshot, no verification footer.

### MCP connection handling (stdioClient async-with pattern)

Use the async-with pattern for the MCP stdio client. Do NOT pre-create the connection via `__aenter__()` and do NOT close the streams manually afterwards — the `stdioclient` generator owns a task group internally, and closing the streams manually (or via `await session.__aexit__()` after the generator is already exiting) triggers `GeneratorExit` and a task-group cancellation bug that raises "Attempted to exit cancel scope in a different task than it was entered in" (a known anyio/mcp bug during event-loop teardown).

**Correct pattern:**
```python
async with stdio_client(server) as (read, write):
    session = ClientSession(read, write, client_info=Implementation(...))
    await session.__aenter__()
    await session.initialize()
    # ... run pipeline ...
    # streams stay alive for the entire pipeline; closing is automatic at
    # the end of the async-with block, which tears down the task group cleanly.
```
Pass the streams into the pipeline by reference; do not extract them and return a dict. The `--environment` and `--execute` arguments live on `args` and are forwarded unchanged into `run_pipeline`.

### Delivery and output capture

The runner script must print the rendered report to **stdout** (not to a file) so the cron wrapper can capture it. The `--deliver-command` argument is optional: when absent, print to stdout; when present, pipe the rendered report into the given command. The same render function is used for both paths — do not hand-compose a separate "cron" message.

### Python string-format safety

When formatting strings that combine user-derived or MCP-derived values, beware of mixing a `:.4f` or `:.2f` format spec on a value that may be a `str`. Before formatting, coerce the value to a numeric type:

```python
price = request.get("limit_price", 0)
if isinstance(price, str):
    price = float(price) if price else 0.0
line = f"...@ €{float(price):.4f}..."
```
Usage of the non-float form (`f"...@ €{price:.4f}..."`) on a `str` raises `ValueError`.

## Standardized completion report

The body follows the Telegram run-template. The report must start immediately with the title line `Trading 212 Run (DEMO / LIVE) - [TIMESTAMP]` — no preamble, no Telegram snapshot, no verification footer. After the Sources block, stop; do not add any closing text.

**Trading 212 Run (DEMO / LIVE) - [TIMESTAMP]**

**Account**
- Balance: €[X] · Free cash: €[Y] · Invested: €[Z] · P/L: €[W]
- Open positions: [N]
- Open orders:
  - [ticker] [side] [qty] @ €[price] (#ID: ID from TIMESTAMP)
  - Example (pending GTC): VWCE BUY 13.5918 @ €165.54 (#ID: 57999972712 from 2026-11-13T19:22)

**Orders this run**
- New: [ticker] [side] [qty] @ €[price] [ORDER TYPE] — ID [ID] [status] — [amount] ([size]%)
- Existing pending preserved: [count]
- Positions: [N] [opened/closed]

**Next actions**
- [action 1] · [action 2]

**Research**
- **Candles**: resolved for [N] ticker(s) — `resolved for 1 ticker` when N=1, `resolved for N tickers` otherwise
- Extraction: succeeded

Only add per-symbol candle errors or extraction diagnostics when a problem exists.

**Sources**
[attribution per source]

End the report at the end of the Sources block — do not add any footer, verification note, or extra closing text.

### Report template updates

- **Account section includes Open orders** listing existing pending or filled orders from `fetch_all_orders`. Render pending orders as mobile-readable one-line records (`TICKER: BUY QTY @ PRICE (ID: ID Since: TIMESTAMP)`); normalize API `NEW` to `PENDING` internally without displaying the status prefix, and map Trading 212 camelCase fields such as `limitPrice` and `createdAt` before formatting.
- **Research combines candle and extraction health**: successful runs show exactly the compact candle-count and extraction-status lines; expand only failing symbols or extraction diagnostics.
- **Remove "Top holdings by value"** — the holdings section is no longer rendered.
- **No "Top holdings by value" API calls** — remove the `fetch_all_open_positions` call from `collect_state` if it is only used for holdings; keep it only if positions count is still needed. The script no longer calls `fetch_all_open_positions` for report data.
- **No preamble, no Telegram snapshot, no verification section** — the report starts immediately with the title and ends after Sources.
- **Environment lives only in the title** — never echo `ENVIRONMENT`/`DEMO`/`LIVE` into the Account or data-quality sections.
- **Report template rendered via script** — use `t212_telegram_template.py` with CLI arguments, never hand-composed. The rendered message is the only thing delivered. The template file lives at `scripts/t212_telegram_template.py` in the profile directory.

## Pitfalls

- **Do not treat a scheduler `ok` status as proof of a valid run report** — inspect the delivered output for account state, order readback, candle status, and extraction status; mark the run failed when the report is malformed or those gates are missing. Never render or deliver Python `None` after an exception: propagate the failure and return nonzero so cron cannot report a false success.
- **Do not widen account state or research context beyond what the selector can process.** The `upstage/solar-mini4:free` model times out at 180s when the selector prompt exceeds the bounded context; verified working bounds are account state <8000 chars and research <6000 chars. Larger contexts (e.g. 12000 chars) can exceed the 180s default and cause the run to stall — reduce, not expand.
- **Do not add repeated per-candidate metadata lookups inside the run.** Each call against the Trading 212 MCP server is rate-limited by the free tier. Load the environment-keyed catalogue cache once, refresh the full universe at most once per TTL, use it to resolve both account and research identities, and pass one deduplicated instrument list to the candle collector; only use bounded per-symbol lookup as a fallback when the universe response lacks the needed identity. Verify a cache hit with a no-network test and verify a first-run refresh with a real read-only catalogue call before declaring the runner usable.
- **Do not accept small-cap or illiquid instruments into a staged order without a live readback of the order.** The `10AKd_EQ` run produced a valid-looking candidate, but the MCP server's `place_limit_order` returned non-JSON data because the instrument is not tradeable with limit orders in the demo account. Always verify the order response contains a valid `id` before reporting a placement.
- **Reconcile the account state before each order, not just before the plan.** Fills and cash reservations from pending orders change buying power between the plan and the write; re-fetch immediately before executing.
- **Do not call a pending order an open position** — Trading 212 can reserve cash while reporting zero invested value until the order fills.
- **Do not rely on a short ticker such as VWCE or VUAA alone** — Trading 212 uses exchange/currency-specific tickers and the wrong listing can create currency exposure or fail validation.
- **Do not place the next tranche from stale balance data** — blocked funds and fills change buying power, so re-fetch cash and orders immediately before sizing.
- **Do not claim a free candle source is working because a fallback returned data** — require a real, parseable response from the named primary source and report the fallback/provider failure distinctly.
- **Do not infer a candle symbol from a short Trading 212 ticker** — verify the exact full Trading 212 ticker, ISIN, and currency first. If Trading 212 omits exchange in the account record, resolve the provider symbol through its search/metadata endpoint and prefer a currency-compatible venue; never silently fall back to a guessed non-EUR listing.
- **Do not report `Candles: None` when account exposure exists** — collect account-source instruments independently of new-order selection and render each result as resolved or unavailable with its reason, because selector output only controls new orders.
- **Do not call the candle collector with a positional ticker when its interface expects an instruments JSON array** — pass the documented `--instruments` payload containing identity fields, because the positional form bypasses validation and can make every candle result look absent.
- **Do not label an existing pending order as new merely because the API status is `NEW`** — normalize that status to `PENDING` in the existing-orders report, because `NEW` describes fill state while run provenance comes from the execution result list.
- **Do not retry permanent Trading 212 order-validation failures** — treat HTTP 4xx placement errors as payload or broker-rule failures, capture the attempted ticker/quantity/limit context and the broker response when available, and stop before repeating the same write.
- **Do not report a scheduler success without validating the rendered message** — a report containing `None`, a missing title, or a missing Account/Research section is a failed run even when the cron record says completed.
- **Make malformed selector output an explicit failure** — initialize the JSON fallback result, raise a clear parse error when no `candidates` object is found, include a bounded raw-output tail, and return nonzero; an unbound local, silent empty output, or discarded timeout output hides the real model failure and can mislead cron.
- **Do not schedule a cron prompt that assumes this chat's context** — cron runs in a fresh session, so missing account, ticker, and guardrail context causes unsafe duplication or skipped verification.
- **Do not promise profit or imply certainty from a current news signal** — market research supports a decision rule, not a guaranteed outcome.
- **Do not diagnose a rapid completion as a 600-second timeout without checking elapsed timestamps.** The report's timeout wording can be emitted by an overly broad exception/fallback path while the selector actually failed fast on permissions, gateway startup, or malformed output. Compare the run log start/end times, inspect the raw selector diagnostic, and classify only `subprocess.TimeoutExpired` as a true wall-clock timeout.
- **Verify the account environment (demo vs live) from the MCP config `mcp_servers.trading212.env.ENVIRONMENT` as the authoritative source, never a job's own summary claim** — a cron job script can emit a wrong environment label (e.g., reporting LIVE when the config says DEMO); cross-check account metadata before labeling.
- **Keep environment out of the body** — it lives only in the title. Never echo `ENVIRONMENT`/`DEMO`/`LIVE` into the Account or data-quality sections; the rendered template already receives it as a title parameter.
- **Manual `hermes cron run` can be discarded at the fire-claim step** — a triggered run may land with status `failed` ("Fire claim ownership lost; stale result was discarded") or `unknown` ("Scheduler restarted after this execution's owner exited before a durable terminal state"). Do not treat it as the run: cross-check `hermes cron runs` for a new completed run and check delivery records before re-triggering or re-verifying Trading 212 state.
- **For cron runs, do not write temp files to /tmp** — the file-mutation verifier flags writes outside `HERMES_WRITE_SAFE_ROOT` (/opt/data). Direct temp writes at the configured `TMPDIR` (the scratch dir), or widen `HERMES_WRITE_SAFE_ROOT` to include it.
- **Do not overwrite a file the session has not read first — clear it, don't patch it.** The `write_file` tool blocks overwriting a file whose current content you have not fully read in this session (file-mutation verifier). Per-run input files such as `$HERMES_HOME/cache/scratch/t212-candle-input.json` persist across runs and must be cleared before rewriting: `rm -f <path>` to start from a clean slate, then write the new run's data. Do not hand-patch existing files you have not fully re-read first.
- **Pin the model to one provider/model.** If the primary model is blocked (HTTP 451), the agent walks `fallback_providers` and tries each fallback, which may also be blocked. Remove the `fallback_providers` entries in `config.yaml` so a blocked primary model fails fast instead of burning retries on models that refuse the request.
- **Parse MCP list results as a JSON stream, not only as one JSON document.** Trading 212 list tools may return concatenated JSON objects or an empty content block for an empty list; decode sequential JSON values and treat empty content as `[]` only for known read-only list calls, while treating empty write responses as unknown state.
- **Do not let the LLM or a stale plan own execution safety.** Re-fetch pending orders, positions, and cash immediately before the write phase because another fill or reservation can invalidate an otherwise valid plan; do not multiply rate-limited calls inside each order loop. Before placement, hard-validate every candidate against the exact Trading 212 instrument identity and broker order constraints; a parsed LLM candidate is not proof that the ticker, venue, price, or quantity is tradeable. Treat permanent 4xx validation responses as non-retryable.
- **Create TP/SL exits from broker state, not the requested buy price.** After BUY writes, collect positions once and use each position's `averagePrice`/`average_price` and current quantity to calculate both configured targets; skip only when pending SELL protection for the same full identity already exists, because the fill may differ from the requested price and quantities can change.
- **Treat missing or orphaned exits as repairable state.** On every run, reconcile all open positions against pending SELL orders, cancel sell orders for positions that no longer exist, and place the missing full-position GTC TP/SL pair; this repairs fills that occurred between cron runs without duplicating exits.
- **Do not replace an integration test with a policy-only test.** Exercise the stdio MCP handshake and one real read-only demo collection before declaring the scripted runner usable; rate limits are expected, so rely on the provider's bounded retry behavior rather than parallel bursts.

## References
- `references/order-planning-gate.md` — catalogue cross-reference gate for order planning: match rule, tradable-record definition, rejection reasons, re-check triggers.
- `references/broker-rejection-flow.md` — order-level broker failure flow (bounded retry boundary, deterministic REJECTED_BY_BROKER rows) and how they carry into the rendered report's Next actions.

## Retrospective pitfalls (learned from user corrections)

## References
- `references/order-planning-gate.md` — catalogue cross-reference gate for order planning: match rule, tradable-record definition, rejection reasons, re-check triggers.
- `references/broker-rejection-flow.md` — order-level broker failure flow (bounded retry boundary, deterministic `REJECTED_BY_BROKER` rows) and how they carry into the rendered report's Next actions.

- **Directory permissions block the LLM gateway.** If `hermes chat` fails with `Gateway inaccessible: unsafe_control_permissions`, check the active profile directory mode before retrying the selector. A group-writable profile directory may be rejected by the gateway's permission check. Remove group/other write permission from `$HERMES_HOME` (for example `chmod go-w "$HERMES_HOME"`), verify the resulting mode, and run `hermes doctor` before rerunning the job.
- **Profile renames require a path audit.** After renaming or moving a profile, search the cron definition, Trading 212 scripts, skill instructions, and `.t212venv/bin` launchers for the old absolute path; repair launchers and make source paths derive from `$HERMES_HOME`, then run `python -m py_compile` plus a read-only MCP handshake before any execution run.
