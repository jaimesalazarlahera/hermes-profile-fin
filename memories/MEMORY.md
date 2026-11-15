Google services are Drive, Calendar, Sheets, and Docs; Gmail and Contacts are excluded.
§
Notes index: /opt/data/notes/NOTES INDEX.md.
§
The [TEST] filename prefix applies only to asset/resource files, not system or internal files.
§
Active Hermes profile: fin at /opt/data/profiles/fin. HERMES_HOME=/opt/data/profiles/fin. Hermes CLI: /opt/hermes/bin/hermes; Hermes venv: /opt/hermes/.venv. The profile runs in the Docker/WSL environment as uid 10000.
§
Trading 212 automation cron: edefd01f8470, every 720m, delivered to Telegram 9238079416. Runner: $HERMES_HOME/scripts/t212_portfolio_automation_cron.py. Trading 212 MCP venv: $HERMES_HOME/.t212venv (Python 3.15); account environment is read from config.yaml at runtime and is currently demo.
§
Trading 212 uses a profile-owned instrument cache and Yahoo Finance as the candle fallback when the primary provider is unavailable. The selector uses the configured model and must return JSON; rate limits and selector timeouts are expected failure modes. Never hardcode profile paths or the demo/live label; resolve them from HERMES_HOME and config.
§
Reusable profile data belongs under $HERMES_HOME/cache/. Do not expose credentials from .env, auth.json, or provider tokens in summaries or logs.
§
Hermes canonical built-in memory files live under `$HERMES_HOME/memories/MEMORY.md` and `USER.md`; root-level `MEMORY.md`/`USER.md` and a singular `memory/` directory are not canonical.
§
Renaming a Hermes profile does not rewrite arbitrary hardcoded paths or virtual-environment launcher shebangs. Profile scripts should resolve paths from `$HERMES_HOME`; after a rename, inspect scripts and generated launchers for the old profile path.