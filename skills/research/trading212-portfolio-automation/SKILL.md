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

Use this skill for Trading 212 account research, conservative portfolio construction, order placement, and recurring monitoring. It is tailored to the user's preference for low-frequency, concise, risk-controlled investing rather than day trading or leverage.

## When to Use

Load this skill when the user asks to inspect a Trading 212 account, research candidate trades, place or manage orders, construct a portfolio, or schedule recurring portfolio monitoring.

## Standing rules

- Treat "maximize profit" as an optimization goal, never a guarantee; state material uncertainty plainly.
- Read the account environment label at runtime from `ENVIRONMENT` under `mcp_servers.trading212.env` in `config.yaml`; state that exact value (e.g. `demo` or `live`) — never hardcode the label here. The account is not fixed to DEMO; if the user switches the config to live, report LIVE.
- Never use leverage, inverse products, CFDs, short positions, or options-income products unless the user explicitly changes this standing policy.
- Never duplicate an existing position, pending order, protective stop, or profit-taking order. Treat matching instrument/side exposure as a hard no-new-order gate unless the user explicitly changes this policy.
- Prefer diversified EUR-denominated UCITS ETFs over concentrated single-stock trades.
- Preserve a cash reserve and use staged entries; do not deploy the full balance on the first run.
- Recurring automation must discover candidates from current account state and current research; do not hardcode specific tickers, funds, exchanges, or fixed allocations into the reusable skill.
- This Trading 212 cron sends its required Telegram summary but does not write to Google Sheets; another job owns that log. Do not access OAuth tokens or bootstrap optional integrations during a run.
- Keep every completion report to the minimum necessary — account state, orders/positions, verification result, and what remains pending — without recap prose. Report concisely: short bullets, state results plainly, and answer directly when asked. A one-word confirmation (e.g. 'OK!') is acceptable for yes/no or state questions.
- Treat market-data provider selection as unverified until a live request returns parseable OHLCV rows. A fallback provider proves only that the fallback worked; report the primary provider as unavailable rather than implying it succeeded.
- Candle-provider errors are per-symbol failures: record the symbol and error, continue with the remaining instruments, and use the fallback provider where configured. Retry only transient 429/408/425/5xx/network failures with bounded exponential backoff; do not retry permanent 4xx errors.
- Validate provider capability with the exact historical `time_series` request, not symbol discovery alone: a symbol can appear in the catalog while historical data is unavailable for the account's plan or market coverage. Report key authentication, symbol resolution, historical entitlement/coverage, rate limiting, and fallback success as separate statuses; never label a configured key missing when the historical endpoint returns 404.
- Keep reusable profile data under `$HERMES_HOME/cache/`; use `$HERMES_HOME/cache/scratch/` only for per-run inputs and temporary files. Do not place candle caches in a global root or inside the skill directory.
- For recurring cron runs, enable scheduler continuity and read only the previous run's `Next actions`/`Next steps` section as provisional context; re-verify every carried-forward action against current account state before acting.

## Procedure

1. **Load account context.** Fetch account info, cash, portfolio summary, all open positions, all pending orders, and recent activity. Record base currency, available cash, invested value, position count, and existing exposure.
2. **Resolve instruments.** Use Trading 212 instrument search for every candidate before ordering. Match the requested fund by ISIN, currency, and exchange-specific ticker; do not infer the ticker from the short name alone.
3. **Research current conditions.** Retrieve current price references and recent company/market information from reliable sources. Every run must invoke both `web_search` and `web_extract`; extract at least one relevant primary or high-quality source even when search snippets appear sufficient. If extraction hits a provider quota or usage limit, stop extraction attempts for that run, continue with search results and available evidence, and state the limit in the Telegram and final reports. Check for imminent earnings or other event risk before opening concentrated positions. Distinguish delayed or historical quotes from live execution prices. If using candles or technical indicators, run a provider preflight for the exact listing, validate the response format, row count, latest date, and symbol/listing identity, and record provider failures separately from successful fallback data.
4. **Design the allocation.** For a new low-frequency EUR portfolio, prefer a broad global ETF core, optionally a smaller broad-US tilt, and explicit cash. Define target weights, entry tranches, order type, and exit/risk rules before placing anything.
5. **Choose execution conservatively.** Prefer staged GTC limit orders when the market is closed, prices are delayed, or the user has not requested immediate market execution. Calculate quantities with a tool, keep total order value within available cash, and leave the reserve uncommitted.
6. **Place orders only after prerequisites pass.** Check current cash, duplicate positions, and all pending orders immediately before each order. Normalize by exact ticker and ISIN, and compare side, quantity, price, and order purpose. If any matching pending order or position exists, do not place another order; preserve the existing order and report the decision. Never duplicate an existing order merely because a prior readback was incomplete. If an order or cancellation call returns an error, timeout, empty response, or parse failure, treat the state as unknown: stop further writes and re-fetch all pending orders before retrying or placing anything else.
7. **Verify external state.** After every state-changing order call, fetch pending orders and portfolio/cash state again. Verify cancellations by confirming the target is absent or cancelled in the readback. Report NEW/PENDING separately from FILLED; never claim a position is open unless the readback shows a filled quantity or an open position.
8. **Protect filled positions.** After a staged ETF order fills, add a non-duplicated protective stop according to the approved risk rule. Re-check existing orders first so one position does not receive multiple exits.
9. **Manage recurring runs.** A cron prompt must be self-contained because scheduled jobs run in a fresh session. Enable scheduler continuity when the job benefits from unfinished next steps, and instruct the run to read only the previous output's `Next actions`/`Next steps` section as provisional context. Re-fetch account context, preserve existing orders, avoid duplicates, verify all writes, send the required Telegram snapshot, and produce a short run summary. Schedule low-frequency checks such as every 12 or 24 hours, not high-speed polling. When a manual run is active, inspect scheduler state or execution records rather than sending follow-up chat messages that may interrupt the run.
10. **Finish with a compact report.** Title the output `Trading 212 Run (DEMO / LIVE) - [TIMESTAMP]` (replace [DEMO/LIVE] from `config.yaml`, [TIMESTAMP] from the run start time), then follow the **Telegram run-template** below — one line only if no orders were placed this run.

## Standardized completion report

The body is the rendered run-template (see the Telegram run-template section). Begin with the title line `Trading 212 Run (DEMO / LIVE) - [TIMESTAMP]` and then the rendered sections — do not add preamble or concluding wrapper. If no orders were placed this run, omit empty order/holdings detail but still include the account, reason, data-quality, and sources blocks.

**Trading 212 Run (DEMO / LIVE) - [TIMESTAMP]**

**Account**
- Balance: €[X] · Free cash: €[Y] · Invested: €[Z] · P/L: €[W]
- Open positions: [N]

**Orders this run**
- New: [ticker] [side] [qty] @ €[price] [ORDER TYPE] — ID [ID] [status] — [amount] ([size]%)
- Existing pending preserved: [count]
- Positions: [N] [opened/closed]

**Top holdings by value**
1. [ticker] — €[X] ([X]%)
2. [ticker] — €[X] ([X]%)
3. [ticker] — €[X] ([X]%)
4. [ticker] — €[X] ([X]%)
5. [ticker] — €[X] ([X]%)
(fewer than five if fewer exist)

**Next actions**
- [action 1] · [action 2]

**Data quality**
- Candles: [provider actually used] · [bar count] bars · latest [date] · [stale/unavailable symbols and reason, if any]
- Extraction: [succeeded / stopped after quota-limit / failed for another reason] · [source used or reason]

**Sources**
[attribution per source]

End the report at the end of the Sources block — do not add any footer, verification note, or extra closing text.

## Telegram run-template

The final response is rendered from the profile's run-template script with parameters — never composed by hand. Feed it the gathered account, order, and market data:

```bash
python /opt/data/profiles/poe/scripts/t212_telegram_template.py \
  --environment <env> --timestamp <ISO run start> --balance <free> \
  --free-cash <free> --invested <invested> --pnl <pnl> --positions <N> \
  --orders <JSON list of order strings> --holdings <JSON list of {ticker,value,pct}> \
  --next-actions <JSON list> --candles <candle status> --extraction <extraction status> \
  --sources <JSON list>
```

The script reads the account environment from the Trading 212 MCP config by default; pass `--environment` only when it differs from the config value. Keep the script's structure exactly as emitted — do not reorder, reword, or add prose around it. That rendered text is both the Telegram summary and the final response.

The rendered message is the **only** thing delivered. Section headings are
**bold** — `**Account**`, `**Orders this run**`, `**Top holdings by value**`,
`**Next actions**`, `**Data quality**`, `**Sources**` — with no other markup:
no `###` headings, no bullet characters, no code fences, no HTML, and no prose
before the `Trading 212 Run (DEMO / LIVE)` title line or after the Sources
block. Nothing first and nothing last.

Environment lives **only** in the title `[DEMO/LIVE]` — never echo `ENVIRONMENT`/`DEMO`/`LIVE` into the Account or data-quality sections.

**Deterministic structure.** Pass every parameter as a CLI argument to the renderer (`--environment`, `--timestamp`, `--balance`, `--free-cash`, `--invested`, `--pnl`, `--positions`, `--orders`, `--holdings`, `--next-actions`, `--candles`, `--extraction`, `--sources`). Identical inputs always produce byte-identical output — re-run the script with the same values and confirm with `diff` before trusting a delivery.

- Read `references/execution-guardrails.md` for the allocation and cron decision tables used by the standing rules.
- Read `references/candle-data.md` for the free Twelve Data/Yahoo candle workflow, profile secret setup, validation, and fallback reporting.
- For new low-frequency portfolio runs, the reference includes a staged allocation table (global core, US tilt, satellite, cash) and decision tables for order type, position sizing, and stop placement.

## Pitfalls

- **Do not treat a scheduler `ok` status as proof of a valid run report** — inspect the delivered output for account state, order readback, candle status, and extraction status; mark the run failed when the report is malformed or those gates are missing.
- **Do not call a pending order an open position** — Trading 212 can reserve cash while reporting zero invested value until the order fills.
- **Do not rely on a short ticker such as VWCE or VUAA alone** — Trading 212 uses exchange/currency-specific tickers and the wrong listing can create currency exposure or fail validation.
- **Do not place the next tranche from stale balance data** — blocked funds and fills change buying power, so re-fetch cash and orders immediately before sizing.
- **Do not claim a free candle source is working because a fallback returned data** — require a real, parseable response from the named primary source and report the fallback/provider failure distinctly.
- **Do not infer a candle symbol from a short Trading 212 ticker** — verify the exact listing by ISIN, exchange, and currency before requesting data, because similarly named ETFs can represent different instruments.
- **Do not schedule a cron prompt that assumes this chat's context** — cron runs in a fresh session, so missing account, ticker, and guardrail context causes unsafe duplication or skipped verification.
- **Do not promise profit or imply certainty from a current news signal** — market research supports a decision rule, not a guaranteed outcome.
- **Do not diagnose rapid start/stop UI changes as a scheduler loop without reading execution state** — manual cron runs can be cancelled when a new user message interrupts the active run; check the job record and execution history, then verify Trading 212 state before retrying.
- **Verify the account environment (demo vs live) from the MCP config `mcp_servers.trading212.env.ENVIRONMENT` as the authoritative source, never a job's own summary claim** — a cron job script can emit a wrong environment label (e.g., reporting LIVE when the config says DEMO); cross-check account metadata before labeling.
- **Keep environment out of the body** — it lives only in the title. Never echo `ENVIRONMENT`/`DEMO`/`LIVE` into the Account or data-quality sections; the rendered template already receives it as a title parameter.
- **Manual `hermes cron run` can be discarded at the fire-claim step** — a triggered run may land with status `failed` ("Fire claim ownership lost; stale result was discarded") or `unknown` ("Scheduler restarted after this execution's owner exited before a durable terminal state"). Do not treat it as the run: cross-check `hermes cron runs` for a new completed run and check delivery records before re-triggering or re-verifying Trading 212 state.
- **For cron runs, do not write temp files to /tmp** — the file-mutation verifier flags writes outside `HERMES_WRITE_SAFE_ROOT` (/opt/data). Direct temp writes at the configured `TMPDIR` (the scratch dir), or widen `HERMES_WRITE_SAFE_ROOT` to include it.
- **Do not overwrite a file the session has not read first — clear it, don't patch it.** The `write_file` tool blocks overwriting a file whose current content you have not fully read in this session (file-mutation verifier). Per-run input files such as `$HERMES_HOME/cache/scratch/t212-candle-input.json` persist across runs and must be cleared before rewriting: `rm -f <path>` to start from a clean slate, then write the new run's data. Do not hand-patch existing files you have not fully re-read first.
- **Pin the model to one provider/model.** If the primary model is blocked (HTTP 451), the agent walks `fallback_providers` and tries each fallback, which may also be blocked. Remove the `fallback_providers` entries in `config.yaml` so a blocked primary model fails fast instead of burning retries on models that refuse the request.
