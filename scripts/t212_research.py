#!/usr/bin/env python3
"""Collect compact, current research for the portfolio selector.

This command performs deterministic web search/extraction only. It does not
choose tickers or place trades; the selector and policy layer do that later.

Research scope (two sources):
  1. Fundamental context on orders already placed (existing positions + pending
     orders) — these are already in the account and are guaranteed tradeable.
  2. Information on NEW positions that could be opened — based on current
     account state (cash, holdings, policy) and current market news/trends.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

os.environ.setdefault("HERMES_HOME", "/opt/data/profiles/poe")
sys.path.insert(0, "/opt/hermes")
from tools.web_tools import web_extract_tool, web_search_tool  # noqa: E402

# Research queries: fundamental analysis + candidate generation.
# Source 2: generate candidate tickers from current news/trends.
QUERIES = (
    # Fundamental context on existing holdings (EUR UCITS ETFs)
    "Vanguard FTSE All-World UCITS ETF EUR Acc (IE00BYV5X256) valuation outlook 2026",
    "VUAA iShares Core MSCI World EUR accumulating valuation outlook 2026",
    "CEBZ iShares Core MSCI Belgium ETF EUR valuation outlook 2026",
    "broad global equity ETF EUR index fund outlook risks catalysts 2026",
    # New position ideas: screens / candidates for the account's EUR UCITS universe
    "best large cap US equities EUR UCITS ETF 2026 top holdings analysis",
    "European equity dividend ETF EUR accumulating screen 2026",
    "defensive global equity ETF EUR low volatility 2026 outlook",
    # Account-state aware: confirm holdings vs cash reserve / staged entries
    "ETF EUR accumulator portfolio rebalance 2026 cash reserve strategy",
)


def search(query: str) -> list[dict[str, Any]]:
    try:
        raw = web_search_tool(query, limit=5)
        payload = json.loads(raw)
        return payload.get("data", {}).get("web", [])
    except Exception as exc:
        return [{"title": "search error", "description": str(exc), "url": ""}]


async def extract(urls: list[str]) -> list[dict[str, Any]]:
    if not urls:
        return []
    try:
        raw = await web_extract_tool(urls[:3], char_limit=3500)
        payload = json.loads(raw)
        return payload.get("results", [])
    except Exception as exc:
        return [{"url": "", "content": "", "error": str(exc)}]


async def main() -> int:
    results = []
    for query in QUERIES:
        results.extend({"query": query, **item} for item in search(query))

    unique = []
    seen = set()
    for item in results:
        url = str(item.get("url") or "")
        if url and url not in seen:
            seen.add(url)
            unique.append(item)
    urls = [str(item["url"]) for item in unique if item.get("url")][:3]
    extracted = await extract(urls)
    valid_extracted = [
        {"url": item.get("url", ""), "content": str(item.get("content", ""))[:3500]}
        for item in extracted if item.get("content")
    ]
    print(json.dumps({
        "queries": list(QUERIES),
        "search_results": unique[:12],
        "extracted": valid_extracted,
        "extraction": "succeeded" if valid_extracted else "failed or unavailable",
        "candles": "deferred until exact Trading 212 instruments are resolved",
        "sources": urls,
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
