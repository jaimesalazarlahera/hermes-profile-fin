# Environment Facts — Hermes Agent (profile: poe)

- Hermes CLI: `/opt/hermes/bin/hermes`; Hermes venv: `/opt/hermes/.venv`.
- Active Hermes profile: `poe` at `/opt/data/profiles/poe`.
- Hermes CLI drops privileges from root to `hermes` user (uid 10000) via `s6-setuidgid`.
- Trading 212 MCP venv: `/opt/data/profiles/poe/.t212venv` (Python 3.15); server binary at `.t212venv/bin/trading212-mcp-server`.
- Trading scripts: `scripts/t212_portfolio_automation.py`, `scripts/t212_research.py`, `scripts/t212_llm.py`, `scripts/t212_telegram_template.py`.
- Skill: `skills/research/trading212-portfolio-automation/SKILL.md`.
- Cron job: `edefd01f8470` (Trading 212 dynamic portfolio automation), every 720m, delivers to Telegram 9238079416.
- Model: `upstage/solar-mini4:free` (Nous Portal).
- `HERMES_WRITE_SAFE_ROOT=/opt/data`; cron executor hardcodes `/tmp` and ignores `TMPDIR`.
- Config: `web_extract.provider=firecrawl`; Trading 212 account = demo (`ENVIRONMENT: demo`).
- `TMPDIR=/opt/data/profiles/poe/cache/scratch`; `HERMES_SITE=/opt/hermes/.venv/lib/python3.14/site-packages`.

## Web search / extract backend

- `web_search` uses the configured backend (default `openai-native` had client-side search issues).
- `web_extract` provider is set in `config.yaml` under `web_extract.provider` (current: `firecrawl`).
- The `firecrawl` package is installed to the user site-packages; the Hermes venv does not include it.
