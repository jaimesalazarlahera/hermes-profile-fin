# Trading 212 portfolio automation script

## Goal

Replace the prompt-driven cron job with a small deterministic runner. The runner owns account reads, safety checks, sizing, order writes, readback verification, report rendering, and delivery. One bounded LLM call proposes candidates; it never gets permission to place orders.

## Pipeline

1. Read environment and run policy from configuration; default to `demo` and dry-run.
2. Fetch account info, cash, positions, pending orders, and recent activity through a single MCP session.
3. Run the configured research command. It must emit JSON and may use web search/extraction and `candle_analysis.py` outside the execution core.
4. Send current state plus research to one LLM call. Require strict JSON containing candidate identity, intended allocation, entry price, and rationale.
5. Resolve each proposed instrument through Trading 212 search and validate exact ISIN, currency, exchange, ETF/type policy, and positive sizing.
6. Re-fetch cash, positions, and pending orders before every candidate. Reject duplicates, reserve 10% cash, enforce staged deployment, and stop on unknown write state.
7. In `--execute` mode, place GTC limit orders only after all gates pass. Immediately fetch each order and refreshed account state. Never label a pending order filled.
8. Render the existing deterministic Telegram template and send the exact rendered text. Write a run artifact with redacted inputs/results.

## Safety contract

- Dry-run is the default; `--execute` is required for writes.
- Live execution additionally requires `--allow-live`.
- No leverage, shorts, CFDs, inverse products, options, or duplicate exposure.
- No order is placed when account reads, instrument resolution, research, LLM output, or verification is incomplete.
- Unknown order-call result stops all further writes and forces a fresh pending-order read.
- The LLM output is untrusted data: schema and policy validation happen in Python.

## First implementation slice

Implement the pure policy layer and adapters first, with tests for duplicate blocking, reserve/staged sizing, exact instrument matching, malformed LLM output, and unknown-write handling. Then wire stdio MCP, OpenAI-compatible LLM, research-command execution, Telegram delivery, and cron migration behind explicit flags. Keep the existing prompt job until a dry-run and a demo execution have produced verified reports.

## Rollout

1. Run `--dry-run` against live account reads with saved research fixture.
2. Compare the generated report with the existing template and inspect rejection reasons.
3. Run in demo with `--execute`; verify every order readback and Telegram delivery.
4. Disable the prompt job only after several successful scheduled demo runs.
5. Promote to live only with an explicit config change and `--allow-live`.
