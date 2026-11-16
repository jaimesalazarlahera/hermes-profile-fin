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
- Distinguish Trading 212 order lifecycle status from run provenance: API `NEW` means an unfilled order, not an order created by the current run. Render existing unfilled orders as `PENDING` in the **Open orders** section, and reserve New orders this run for orders actually placed during this execution.
- **Only trade distributing (Dist) tickers** — when the goal is periodic cash extraction, reject accumulating tickers. Trading 212 tickers encode the distribution policy in the suffix: `d_EQ` / `l_EQ` = distributing, `m_EQ` / `a_EQ` = accumulating. Apply this filter in the order-planning step before any order is built; a candidate is rejected with `accumulating (not distributing) - filtered out` if it is not distributing.
- **Report tickers are suffix-stripped** — display `VUAA`, not `VUAAm_EQ` — via `_strip_ticker_suffix` in the report template; underlying instrument identity (ISIN/price/quantity) preserves the full Ticker.
- **Report one-line** — render Current orders as compact mobile-readable one-line records in the form `TICKER: BUY QTY @ PRICE (ID: <order_id> Since: <timestamp>)`. Do not use a wide table, status prefix, bullet card, `#` marker, or currency symbol in this line; preserve the full ticker and exact API values.
- Combine candle and extraction health into one Research section. On success render only `- Candles: resolved for N tickers` and `- Extraction: succeeded`; include per-symbol candle errors or extraction diagnostics only when an issue exists.
- Prefer diversified EUR-denominated UCITS ETFs over concentrated single-stock trades.
- Preserve a cash reserve and use staged entries; do not deploy the full balance on the first run.
- Recurring automation must discover candidates from current account state and current research; do not hardcode specific tickers, funds, exchanges, or fixed allocations into the reusable skill.
- This Trading 212 cron sends its required Telegram summary but does not write to Google Sheets; another job owns that log. Do not access OAuth tokens or bootstrap optional integrations during a run.
- Keep every completion report to the minimum necessary — account state, orders/positions, verification result, and what remains pending — without recap prose. Report concisely: short bullets, state results plainly, and answer directly when asked. A one-word confirmation (e.g. 'OK!') is acceptable for yes/no or state questions.
- **Credential-handling rule:** never preserve API keys, tokens, passwords, secrets, connection strings, or credentials in any summary, report, or log output — replace with [REDACTED]. Applies to Trading 212 API keys, MCP auth, Telegram bot tokens, and any other credentials.
- Treat market-data provider selection as unverified until a live request returns parseable OHLCV rows. A fallback provider proves only that the fallback worked; report the primary provider as unavailable rather than implying it succeeded.
- Candle-provider errors are per-symbol failures: record the symbol and error, continue with the remaining instruments, and use the fallback provider where configured. Retry only transient 429/408/425/5xx/network failures with bounded exponential backoff; do not retry permanent 4xx errors.
- The candle set must always be the union of open positions, pending orders, and research-selected candidates. Never set candles to `None` merely because the selector produced no new order candidates; an empty new-order plan does not mean the account source is empty.
- Preserve the full Trading 212 identity for every candle request: exact full ticker, ISIN, and currency. Trading 212 list/order records may omit exchange, so let the provider resolver fill a verified venue mapping; do not reject an otherwise complete account instrument only because the exchange field is absent.
- Validate provider capability with the exact historical `time_series` request, not symbol discovery alone: a symbol can appear in the catalog while historical data is unavailable for the account's plan or market coverage. Report key authentication, symbol resolution, historical entitlement/coverage, rate limiting, and fallback success as separate statuses; never label a configured key missing when the historical endpoint returns 404.
- Keep reusable profile data under `$HERMES_HOME/cache/`; use `$HERMES_HOME/cache/scratch/` only for per-run inputs and temporary files. Do not place candle caches in a global root or inside the skill directory.
- Resolve every runner, config, cache, MCP, and LLM path from `$HERMES_HOME`; never embed a profile's absolute name in reusable scripts or cron wrappers, because profile renames otherwise leave jobs pointing at the old path.
- For recurring cron runs, enable scheduler continuity and read only the previous run's `Next actions`/`Next steps` section as provisional context; re-verify every carried-forward action against current account state before acting.
- When implementing recurring automation as a script, keep the LLM limited to research/candidate selection; Python must own state reads, identity validation, sizing, duplicate gates, writes, readbacks, rendering, and delivery.
- Make dry-run the default for new or unapproved runners; once the user authorizes scheduled execution, the cron wrapper must pass `--execute`. Treat the configured `ENVIRONMENT` as the authoritative demo/live target, not as a substitute for the execution flag; require a separate explicit live-environment approval gate.
- **Selector constraints should be calibrated to the model, not assumed strict.** The default selector is conservative and may reject candidates that are technically valid. After an empty `{"candidates": []}` result, relax constraints in this order: (1) allocation upper bound `0 < x <= 1`; (2) accept ISIN-exact or partial ticker match; (3) widen context only to verified working bounds. Re-validate every candidate through the cached Trading 212 catalogue after relaxation — never accept a candidate the model fabricates.
- When using scripted candidate selection, maintain a profile-owned Trading 212 instrument catalogue cache keyed by environment (for example `$HERMES_HOME/cache/trading212/instruments-demo.json`); store `fetched_at`, environment, count, and raw records, write updates atomically, refresh it about every 24 hours, and use its exact ticker/ISIN records for the current EUR ETF universe. Load the catalogue once per run and include only relevant exact records in the LLM input. On refresh rate limits, use a bounded-age stale cache for research but do not place new orders once the cache exceeds its hard maximum age; force refresh after an unknown ticker or broker rejection. Never let the model invent identifiers from web research or memory.
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
- **Account state is fetched once at the start and cached.** `collect_state` (account info, cash, positions, orders, recent activity) runs once; subsequent runs must not re-fetch account info per order. `execute_orders` adds only 2 calls per new order (place + readback). Do not re-fetch cached account data inside order loops.

## Hermes config and toolchain setup (one-time)

- Set the web search/extract backend explicitly (default `auto` → `openai-native` fails on client-side search). `config.yaml` per-provider timeouts must be raised for the slow free-tier models:

```bash
hermes config set web_extract.provider firecrawl
hermes config set providers.nous.request_timeout_seconds 300
hermes config set providers.nous.stale_timeout_seconds 900
```

- `firecrawl` package lives in the profile's user site-packages (`$HERMES_HOME/home/.local/lib/python3.14/site-packages`) but is not visible to the Hermes venv by default. When running research/LLM commands, export `PYTHONPATH=$HERMES_HOME/home/.local/lib/python3.14/site-packages`. The `hermes chat` adapter (`t212_llm.py`) must run from the profile directory itself: it sets `HERMES_HOME`, `HOME`, and `PATH` explicitly, and its `subprocess.run` passes `--query-file - --oneshot -Q --format text --max-turns 10` so the bounded model returns JSON-only output. If the adapter's CWD is not the profile directory, `hermes chat` fails to resolve the skills/gateway; run from the profile root.

## Pipeline health checks

- Before running the full pipeline, verify `pydantic_core` C extension imports in the MCP server's venv (`$HERMES_HOME/.t212venv`, Python 3.15): `import pydantic_core`. If it fails with "No module named 'pydantic_core._pydantic_core'", the `.so` was lost during a prior reinstall. Reinstall with `python -m ensurepip --default-pip` then `pip install --force-reinstall pydantic_core==2.50.4` inside the venv and re-check by importing, not just by file presence. Also verify `pydantic==2.14.3` is consistent with `pydantic_core==2.50.4`.

## Procedure

0. **Validate profile portability before execution.** Confirm `HERMES_HOME` is the intended profile, audit executable source and launcher paths for stale profile names, verify the MCP launcher interpreter and `pydantic_core` import, and run a read-only MCP collection before enabling `--execute`.
1. **Load metadata and account context.** Load the environment-keyed instrument catalogue from the profile cache; refresh it once when older than the TTL, and fall back only to a bounded-age stale copy. Then fetch account info, cash, portfolio summary, all open positions, all pending orders, and recent activity. Record base currency, available cash, invested value, position count, and existing exposure. **Account state and catalogue are fetched once at the start and cached** — never issue repeated per-candidate metadata lookups or re-fetch account state inside order loops.
2. **Research current conditions.** Run the deterministic research command (web_search + web_extract) to gather current conditions and candidate tickers. Research supplies evidence; it does not choose tickers.
3. **Merge candidate tickers from 2 sources.** Source 1: existing open positions and pending orders (guaranteed tradeable). Source 2: research candidates from news/trends. Resolve exact trading instruments from Trading 212 metadata.
4. **Resolve candles.** Build the union of all open-position tickers, all pending-order tickers, and research-selected tickers; resolve missing Trading 212 metadata before collection; then invoke the candle collector once for the complete union. Record per-symbol provider, bar count, latest date, and error. A run with no new orders must still report candles for the account-source tickers.
5. **Bounded LLM selector call.** Resolve the selector model/provider from the cron job configuration, send one compact tool-free prompt (account state + research + candle status), and require JSON-only output. Accept an explicit empty `{"candidates": []}` result and relax constraints in order (1) allocation_pct upper bound `0 < x <= 1`; (2) ISIN-exact OR partial ticker match; (3) widen context only to verified working bounds. Treat timeout, non-zero exit, or malformed output as a failed run and preserve the raw selector output tail in diagnostics.
6. **Order planning.** Build the order plan from new candidates only (exclude already-positioned/pending tickers). Validate sizes against cached cash and check duplicates.
7. **Order execution.** No more than 2 endpoints per NEW order: `place_limit_order` (1 call) + `fetch_order` readback (1 call). Do not re-fetch account state inside the order loop — use cached state for preflight.
8. **Render and deliver.** Render the standardized report template (see Template format section below). No preamble, no Telegram snapshot, no verification footer.

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
- **Do not let the LLM or a stale plan own execution safety.** Re-fetch pending orders, positions, and cash immediately before each order because another fill or reservation can invalidate an otherwise valid plan. Before placement, hard-validate every candidate against the exact Trading 212 instrument identity and broker order constraints; a parsed LLM candidate is not proof that the ticker, venue, price, or quantity is tradeable. Treat permanent 4xx validation responses as non-retryable.
- **Do not replace an integration test with a policy-only test.** Exercise the stdio MCP handshake and one real read-only demo collection before declaring the scripted runner usable; rate limits are expected, so rely on the provider's bounded retry behavior rather than parallel bursts.

## Retrospective pitfalls (learned from user corrections)

- **Directory permissions block the LLM gateway.** If `hermes chat` fails with `Gateway inaccessible: unsafe_control_permissions`, check the active profile directory mode before retrying the selector. A group-writable profile directory may be rejected by the gateway's permission check. Remove group/other write permission from `$HERMES_HOME` (for example `chmod go-w "$HERMES_HOME"`), verify the resulting mode, and run `hermes doctor` before rerunning the job.
- **Profile renames require a path audit.** After renaming or moving a profile, search the cron definition, Trading 212 scripts, skill instructions, and `.t212venv/bin` launchers for the old absolute path; repair launchers and make source paths derive from `$HERMES_HOME`, then run `python -m py_compile` plus a read-only MCP handshake before any execution run.
