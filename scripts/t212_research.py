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
import hashlib
import json
import os
import sys
from typing import Any

os.environ.setdefault("HERMES_HOME", "/opt/data")
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


# Transient extraction failures worth retrying (rate limits, timeouts, 5xx,
# network blips). Permanent 4xx (401/403/404, paywalls) are NOT retried.
_TRANSIENT_TOKENS = ("429", "408", "425", "500", "502", "503", "504", "timed out", "timeout", "connection", "network")


def _is_transient_error(error: str) -> bool:
    text = error.lower()
    return any(token in text for token in _TRANSIENT_TOKENS)


def _looks_like_junk(content: str) -> bool:
    """True when the scraped page is an interstitial/diagnostic page, not
    real readable content. These pages are useless (and confusing) to the
    selector, so they are dropped rather than fed to it."""
    low = content.lower()
    markers = (
        "relevance inspector", "ignoreopen", "connecting:",
        "forwarded:", "lighthouse", "ux-audit",
        "javascript is required", "similarweb", "chrome insp",
        "next.js", "__next", "page render", "fonts.googleapis",
    )
    return any(marker in low for marker in markers)


def _usable_content(content: str) -> bool:
    return len(" ".join(content.split())) >= 200 and not _looks_like_junk(content)


def _usable_search_result(item: dict[str, Any]) -> bool:
    title = " ".join(str(item.get("title") or "").split()).lower()
    query = " ".join(str(item.get("query") or "").split()).lower()
    description = str(item.get("description") or "")
    if not title or (query and title == query):
        return False
    return not _looks_like_junk(f"{title} {description}")


def _dedupe_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicates by URL, then by normalized title/description."""
    seen_url: set[str] = set()
    seen_hash: set[str] = set()
    out = []
    for item in items:
        url = str(item.get("url") or "").strip()
        if url and url in seen_url:
            continue
        seen_url.add(url)
        text = " ".join(
            f"{item.get('title') or ''} {item.get('description') or ''}".lower().split()
        )
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        if digest in seen_hash:
            continue
        seen_hash.add(digest)
        out.append(item)
    return out


async def extract(urls: list[str]) -> list[dict[str, Any]]:
    """Extract up to 3 URLs, retrying only transient per-URL failures.

    Bounded exponential backoff (2s -> 4s -> 8s, cap 30s, 4 attempts total),
    matching the pipeline's MCP retry convention. Successful URLs are never
    re-scraped; only URLs with transient errors are retried.
    """
    if not urls:
        return []
    urls = urls[:3]
    max_attempts = 4
    base_delay = 2.0
    results: dict[str, dict[str, Any]] = {}
    pending = list(urls)
    for attempt in range(1, max_attempts + 1):
        try:
            raw = await web_extract_tool(pending, char_limit=3500)
            payload = json.loads(raw)
            items = payload.get("results", [])
            if not items and payload.get("error"):
                items = [{"url": u, "content": "", "error": str(payload["error"])} for u in pending]
        except Exception as exc:
            items = [{"url": u, "content": "", "error": str(exc)} for u in pending]
        by_url = {str(item.get("url") or ""): item for item in items}
        retry_urls = []
        for index, url in enumerate(pending):
            if len(items) == len(pending):
                item = items[index]
            else:
                item = by_url.get(url) or {"url": url, "content": "", "error": "no result returned"}
            results[url] = item
            content = str(item.get("content") or "")
            # Junk/interstitial pages are NOT retried: re-scraping them does
            # not produce usable content and just wastes extraction quota.
            if content and _looks_like_junk(content):
                item["error"] = "junk or interstitial page (dropped)"
                item["content"] = ""
            error = str(item.get("error") or "")
            if error and _is_transient_error(error) and attempt < max_attempts:
                retry_urls.append(url)
        if not retry_urls:
            break
        wait = min(base_delay * (2 ** (attempt - 1)), 30.0)
        print(
            f"  [research] extraction transient failure on {len(retry_urls)} url(s); "
            f"retry {attempt}/{max_attempts - 1} in {wait:.1f}s",
            file=sys.stderr,
        )
        await asyncio.sleep(wait)
        pending = retry_urls
    return [results[url] for url in urls]


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
    raw_search_results = _dedupe_results(unique)
    usable = [r for r in raw_search_results if _usable_search_result(r)]
    # Extract up to 6 non-junk targets; structured sources are preferred.
    def _rank(item: dict[str, Any]) -> int:
        url = str(item.get("url") or "").lower()
        good_hints = ("factsheet", "snapshotresearch", "tipranks", "stocktrademastery",
                      "lightyear", "perplexity", "ishares", "nl.vanguard", "vnif", "knight")
        return 0 if any(h in url for h in good_hints) else 1

    usable = sorted(usable, key=_rank)
    urls = [str(item["url"]) for item in usable[:6] if item.get("url")]
    extracted = await extract(urls)
    usable_search = [r for r in raw_search_results if _usable_search_result(r)]
    valid_extracted = [
        {"url": item.get("url", ""), "content": str(item.get("content", ""))[:3500]}
        for item in extracted if item.get("content")
    ]
    usable_extracted = [e for e in valid_extracted if _usable_content(e["content"])]
    # Preserve the failure reason so the run report can say WHY extraction
    # failed instead of a generic status. Junk/interstitial pages are counted
    # as unusable content, not retried (see extract()).
    reasons = []
    if not usable_extracted and extracted:
        for item in extracted:
            err = str(item.get("error") or "").strip()
            if err:
                reasons.append(f"{item.get('url') or 'batch'}: {err}")
            elif not item.get("content"):
                reasons.append(f"{item.get('url') or 'batch'}: no content returned")
            elif _looks_like_junk(str(item.get("content", ""))):
                reasons.append(f"{item.get('url') or 'batch'}: junk/interstitial page")
    elif not usable_extracted:
        reasons.append("no extractable content returned")
    extraction_status = "succeeded" if usable_extracted else f"no usable content ({'; '.join(reasons)[:200]})"
    print(json.dumps({
        "queries": list(QUERIES),
        "search_results": usable_search[:12],
        "extracted": usable_extracted,
        "extraction": extraction_status,
        "candles": "deferred until exact Trading 212 instruments are resolved",
        "sources": urls + [r.get("url", "") for r in raw_search_results],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
