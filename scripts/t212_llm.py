#!/usr/bin/env python3
"""Single bounded LLM adapter for the portfolio candidate selector."""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERMES = "/opt/hermes/bin/hermes"


def extract_object(text: str) -> dict:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "candidates" in value:
            return value
    raise ValueError("LLM did not return a candidates JSON object")


def call_hermes(prompt: str) -> str:
    env = dict(os.environ)
    env["HERMES_HOME"] = "/opt/data/profiles/poe"
    env["HOME"] = "/opt/data/profiles/poe"
    env["PATH"] = "/opt/hermes/bin:/opt/hermes/.venv/bin:" + env.get("PATH", "")
    try:
        completed = subprocess.run(
            [HERMES, "chat", "--query-file", "-", "--oneshot", "-Q", "--format", "text", "--max-turns", "10"],
            input=prompt, capture_output=True, text=True, env=env, timeout=300, check=True,
        )
        return completed.stdout
    except subprocess.CalledProcessError as exc:
        # Hermes chat exits non-zero when the model runs out of steps; fall back to raw output.
        return exc.stdout or exc.stderr or ""


def main() -> int:
    prompt = sys.stdin.read()
    if not prompt.strip():
        raise SystemExit("empty selector prompt")
    prompt += (
        "\nReturn ONLY one JSON object. Do not use markdown fences, commentary, "
        "tool calls, or additional keys. If evidence is insufficient, return "
        '{"candidates":[]}.'
    )
    text = call_hermes(prompt)
    try:
        candidate = extract_object(text)
    except ValueError:
        # Fallback: scan for the first { ... } JSON object containing "candidates".
        decoder = json.JSONDecoder()
        candidate = None
        idx = 0
        while idx < len(text):
            while idx < len(text) and text[idx].isspace():
                idx += 1
            if idx >= len(text):
                break
            if text[idx] != "{":
                idx += 1
                continue
            try:
                value, end = decoder.raw_decode(text, idx)
            except json.JSONDecodeError:
                idx += 1
                continue
            if isinstance(value, dict) and "candidates" in value:
                candidate = value
                break
            idx = end
        if candidate is None:
            raw = text[-4000:] if text else "<empty selector output>"
            raise ValueError(f"LLM did not return a candidates JSON object. Raw selector output (tail):\n{raw}")
    print(json.dumps(candidate, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else str(exc)
        print(f"selector failed: {detail[-1000:]}", file=sys.stderr)
        raise SystemExit(2)
    except (subprocess.TimeoutExpired, ValueError) as exc:
        print(f"selector failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
