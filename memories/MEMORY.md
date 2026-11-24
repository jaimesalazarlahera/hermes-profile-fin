Google services are Drive, Calendar, Sheets, and Docs; Gmail and Contacts are excluded.
§
Notes index: /opt/data/notes/NOTES INDEX.md.
§
The [TEST] filename prefix applies only to asset/resource files, not system or internal files.
§
Active Hermes profile: fin at /opt/data/profiles/fin. HERMES_HOME=/opt/data/profiles/fin. Hermes CLI: /opt/hermes/bin/hermes; Hermes venv: /opt/hermes/.venv. The profile runs in the Docker/WSL environment as uid 10000.
§
Trading 212 uses a profile-owned instrument cache and Yahoo Finance as the candle fallback when the primary provider is unavailable. The selector uses the configured model and must return JSON; rate limits and selector timeouts are expected failure modes. Never hardcode profile paths or the demo/live label; resolve them from HERMES_HOME and config.
§
Reusable profile data belongs under $HERMES_HOME/cache/. Do not expose credentials from .env, auth.json, or provider tokens in summaries or logs.
§
Hermes canonical built-in memory files live under `$HERMES_HOME/memories/MEMORY.md` and `USER.md`; root-level `MEMORY.md`/`USER.md` and a singular `memory/` directory are not canonical.
§
Renaming a Hermes profile does not rewrite arbitrary hardcoded paths or virtual-environment launcher shebangs. Profile scripts should resolve paths from `$HERMES_HOME`; after a rename, inspect scripts and generated launchers for the old profile path.
§
Trading 212 ticker suffixes encode listing venue (d=Xetra, a=Amsterdam, l=London, s=Swiss, m=Milan), NOT distribution policy; Acc/Dist is authoritative only via '(Acc)'/'(Dist)' in the instrument name. VWCEd_EQ and CEBZd_EQ are accumulating.
§
Trading 212 research verification: quality-gate tests use `/opt/hermes/.venv/bin/python` plus profile user-site PYTHONPATH; the MCP `.t212venv` lacks Hermes web dependencies. Use unittest discovery, not direct function-style test execution. The gate filters junk/interstitial pages, requires >=200 readable characters, deduplicates normalized results, and rotates up to six structured targets.