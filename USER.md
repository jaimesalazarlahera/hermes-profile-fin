# User Profile

## Persona
Personal, low-frequency stock/ETF investor. Starting balance ~€20,000, scales to €100+. NOT day trading, NOT medium/long-term holding — purchases every few days/weeks. Prefers dynamic candidate selection based on current conditions; technical analysis allowed as one input.

## Service Set
Drive, Calendar, Sheets, Docs (Gmail and Contacts excluded).

## Communication Style
Concise and direct; one-word replies acceptable (e.g., 'OK!'). Standardized, template-driven reports — no preamble, no extra sections, no Telegram-snapshot-style additions. Begin immediately with the run title, end at Sources with no footer.

## Expectations
- Confirm account DEMO vs LIVE before any state-changing call; apply real-account-grade controls even on demo.
- Never use leverage, inverse products, CFDs, short positions, or options-income products unless explicitly changed.
- Prefer diversified EUR-denominated UCITS ETFs over concentrated single-stock trades.
- Preserve cash reserve; staged entries; do not deploy full balance on first run.
- Recurring automation must discover candidates from current account state and current research; no hardcoded tickers/funds/exchanges/fixed allocations.
- Preference: **trade distributing (Dist) tickers only** — for periodic cash extraction, reject accumulating tickers (Trading 212 suffixes `d_EQ`/`l_EQ` = distributing, `m_EQ`/`a_EQ` = accumulating; apply in `build_order_plan`).
- Report tickers are **suffix-stripped** — display `VUAA` not `VUAAm_EQ` — via `_strip_ticker_suffix` in the report template; underlying instrument identity (ISIN/price/quantity) preserves the full Ticker.
- Each run summarized to Telegram with balance/cash, top five assets, orders and positions changed, exits added, and likely next actions.
- Each run summarized to Telegram with balance/cash, top five assets, orders and positions changed, exits added, likely next actions.
- Research log, orders tracking, and Telegram summaries via Google Sheets.
