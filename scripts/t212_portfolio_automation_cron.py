#!/usr/bin/env python3
"""Cron entrypoint for the deterministic Trading 212 runner."""
from __future__ import annotations

import os
import re
import subprocess
import sys

PYTHON = "/opt/hermes/.venv/bin/python"
ROOT = "/opt/data/profiles/poe/scripts"
CONFIG = "/opt/data/profiles/poe/config.yaml"


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


cmd = [
    PYTHON,
    f"{ROOT}/t212_portfolio_automation.py",
    "--research-command", f"{PYTHON} {ROOT}/t212_research.py",
    "--llm-command", f"{PYTHON} {ROOT}/t212_llm.py",
    "--environment", environment(),
    "--execute",
]
if environment().lower() == "live":
    if os.environ.get("T212_ALLOW_LIVE") != "1":
        print("Refusing live execution: set T212_ALLOW_LIVE=1 explicitly.", file=sys.stderr)
        sys.exit(2)
    cmd.append("--allow-live")

# Build the output log file path under the profile-owned scratch directory.
import datetime
from pathlib import Path

log_dir = Path(os.environ.get("HERMES_HOME", "/opt/data")) / "cache" / "scratch"
log_dir.mkdir(parents=True, exist_ok=True)
log_path = log_dir / f"t212-run-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')}.log"

completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
# Save the full output (stdout + stderr) to the log file
with log_path.open("w", encoding="utf-8") as fh:
    fh.write(completed.stdout)
    if completed.stderr:
        fh.write(completed.stderr)
# Print the output so the Hermes platform captures it
print(completed.stdout, end="")
if completed.stderr:
    print(completed.stderr, end="", file=sys.stderr)

sys.exit(completed.returncode)
