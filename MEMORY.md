# Environment Notes — Trading 212 Portfolio Automation

## Paths & Accounts
- Profile: `poe` at `/opt/data/profiles/poe`
- Working dir: `/opt/data/profiles/poe` (run as `hermes` uid 10000, WSL)
- Cron job: `edefd01f8470` — "Trading 212 dynamic portfolio automation", schedule every 720m
- Cron script: `/opt/data/profiles/poe/scripts/t212_portfolio_automation_cron.py`
- Trading 212 MCP server venv: `/opt/data/profiles/poe/.t212venv` (Python 3.15)
- Trading 212 MCP server binary: `/opt/data/profiles/poe/.t212venv/bin/trading212-mcp-server`
- Trading 212 demo account: `mcp_servers.trading212.env.ENVIRONMENT: demo` (in config.yaml)
- Trading 212 API keys: `TRADING212_API_KEY`, `TRADING212_API_SECRET` — not set in `.env` by default; placeholder used until credentials are provided

## Environment Variables
- `HERMES_HOME=/opt/data/profiles/poe`
- `HERMES_WRITE_SAFE_ROOT=/opt/data` (safe root for file mutations)
- `TMPDIR=/opt/data/profiles/poe/cache/scratch` (set but executor hardcodes `/tmp`)

## Config Files
- `config.yaml`: model default `upstage/solar-mini4:free`; `mcp_servers.trading212.env.ENVIRONMENT: demo`
- `cron/jobs.json`: job `edefd01f8470` (scheduled every 720m)

## Web Search / Extract
- Backend: `firecrawl` (config: `web.extract_backend: firecrawl`, `web_extract.provider: firecrawl`)
- `firecrawl` package lives in user site-packages: `/opt/data/profiles/poe/home/.local/lib/python3.14/site-packages`
- Not visible to the Hermes venv by default — set `PYTHONPATH` when running research/LLM commands:
  ```bash
  export PYTHONPATH=/opt/data/profiles/poe/home/.local/lib/python3.14/site-packages
  ```

## File Mutation Safety (CRITICAL)
- `HERMES_WRITE_SAFE_ROOT=/opt/data` — file writes outside this root are flagged by the verifier
- The Hermes cron executor hardcodes `/tmp` for temp files and does NOT honor `TMPDIR`
- `/tmp` is outside the safe root → `/tmp/check_env.py` fails verification on cron runs
- Fix options:
  1. Set `PYTHONPATH` to include the user site-packages (recommended — firecrawl lives there)
  2. Widen `HERMES_WRITE_SAFE_ROOT` to include `/tmp` (only if you control the executor source)

## Trading 212 MCP Server
- Venv: `/opt/data/profiles/poe/.t212venv` (Python 3.15), different from Hermes venv (Python 3.14)
- The `pydantic_core` C extension was broken in a prior fix attempt; reinstalled 2.50.4 → `_pydantic_core.cpython-315-x86_64-linux-gnu.so` restored
- Verify `import pydantic_core` works inside the venv before running the pipeline
- **Demo account was reset on 2026-11-13** — all pending orders, positions, and open orders cleared (verify `equity/history/transactions?limit=2` returns `0` before running)

## Cron Job Model & Selector
- Cron runs with `/opt/hermes/.venv/bin/python` (Python 3.14)
- Selector: `/opt/data/profiles/poe/scripts/t212_llm.py` → calls `hermes chat --query-file - --oneshot`
- Model: `upstage/solar-mini4:free` (config: `model.default`)
- Selector prompt must be simple JSON schema; complex prompts cause the model to return natural-language instead of JSON
- **LLM selector is slow** — a full run can exceed 300s at the free model's rate; run the cron job with explicit timeout (e.g. `timeout 600`)

## Report Template (standard for all cron runs)
Title: `Trading 212 Run (DEMO / LIVE) - [TIMESTAMP]`
Sections: **Account** (Balance, Free cash, Invested, P/L, Open positions) · **Orders this run** · **Top holdings by value** · **Next actions** · **Data quality** · **Sources**
Rules: no preamble, no Telegram snapshot, no footer, no verification note. End at Sources.

## Recent Run States
- Last successful run: `2026-11-12_17-41-20.md` (error: LLM selector returned empty/invalid)
- Last manual run: `2026-11-12_17-54-20.md` (error: ProposalError — invalid price/allocation)
