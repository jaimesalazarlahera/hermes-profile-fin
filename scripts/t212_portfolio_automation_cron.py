#!/usr/bin/env python3
"""Cron entrypoint for the deterministic Trading 212 runner."""
from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PYTHON = "/opt/hermes/.venv/bin/python"
PROFILE_HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
ROOT = PROFILE_HOME / "scripts"
CONFIG = PROFILE_HOME / "config.yaml"


def environment() -> str:
    configured = os.environ.get("T212_ENVIRONMENT", "").strip()
    if configured:
        return configured
    try:
        text = open(CONFIG, encoding="utf-8").read()
        match = re.search(r"^\s*ENVIRONMENT:\s*(\S+)", text, re.MULTILINE)
        if match:
            return match.group(1)
    except OSError:
        pass
    return "unknown"


def selector_overrides() -> tuple[str | None, str | None]:
    """Read optional model/provider pins from this script's cron job."""
    model = os.environ.get("T212_SELECTOR_MODEL") or None
    provider = os.environ.get("T212_SELECTOR_PROVIDER") or None
    jobs_path = PROFILE_HOME / "cron" / "jobs.json"
    try:
        payload = json.loads(jobs_path.read_text(encoding="utf-8"))
        for job in payload.get("jobs", []):
            if Path(str(job.get("script", ""))).name != Path(__file__).name:
                continue
            model = model or job.get("model") or None
            provider = provider or job.get("provider") or None
            break
    except (OSError, TypeError, ValueError):
        pass
    return model, provider


selector_model, selector_provider = selector_overrides()
print(
    f"  [t212] selector model: {selector_model or 'profile default'}; "
    f"provider: {selector_provider or 'profile default'}",
    file=sys.stderr,
)
llm_command = [PYTHON, str(ROOT / "t212_llm.py")]
if selector_model:
    llm_command.extend(["--model", selector_model])
if selector_provider:
    llm_command.extend(["--provider", selector_provider])

cmd = [
    PYTHON,
    f"{ROOT}/t212_portfolio_automation.py",
    "--research-command", shlex.join([PYTHON, str(ROOT / "t212_research.py")]),
    "--llm-command", shlex.join(llm_command),
    "--environment", environment(),
    "--execute",
]
if environment().lower() == "live":
    if os.environ.get("T212_ALLOW_LIVE") != "1":
        print("Refusing live execution: set T212_ALLOW_LIVE=1 explicitly.", file=sys.stderr)
        sys.exit(2)
    cmd.append("--allow-live")

# Build the output log file path under the profile-owned scratch directory.
log_dir = Path(os.environ.get("HERMES_HOME", "/opt/data")) / "cache" / "scratch"
log_dir.mkdir(parents=True, exist_ok=True)
log_path = log_dir / f"t212-run-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')}.log"

completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
# Save the full output (stdout + stderr) to the log file.
selector_log = (
    f"[t212] selector model: {selector_model or 'profile default'}; "
    f"provider: {selector_provider or 'profile default'}\n"
)
with log_path.open("w", encoding="utf-8") as fh:
    fh.write(selector_log)
    fh.write(completed.stdout)
    if completed.stderr:
        fh.write(completed.stderr)
# Print the output so the Hermes platform captures it
print(completed.stdout, end="")
if completed.stderr:
    print(completed.stderr, end="", file=sys.stderr)

sys.exit(completed.returncode)
