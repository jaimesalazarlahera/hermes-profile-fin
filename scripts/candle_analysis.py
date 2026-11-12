#!/usr/bin/env python3
"""Free daily OHLCV candles with Twelve Data primary and Yahoo fallback.

Input instruments must contain explicit provider symbols verified for the exact
Trading 212 listing. No ticker guessing or ETF substitution is performed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "poe-trading212-candle-analysis/1.0"
DEFAULT_DAYS = 400
CACHE_TTL_SECONDS = 20 * 60


def _request(url: str, *, timeout: int = 20) -> bytes:
    """Fetch a URL, retrying transient rate/server failures with backoff."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {408, 425, 429} or 500 <= exc.code <= 599
            if not retryable or attempt == 3:
                raise
            retry_after = exc.headers.get("Retry-After", "")
            try:
                delay = min(30.0, max(1.0, float(retry_after)))
            except (TypeError, ValueError):
                delay = min(30.0, 2.0 ** attempt)
            time.sleep(delay)
        except urllib.error.URLError:
            if attempt == 3:
                raise
            time.sleep(min(30.0, 2.0 ** attempt))
    raise RuntimeError("request retry loop exhausted")


def _http_json(url: str, *, timeout: int = 20) -> Any:
    return json.loads(_request(url, timeout=timeout).decode("utf-8"))


def _http_text(url: str, *, timeout: int = 20) -> str:
    return _request(url, timeout=timeout).decode("utf-8")


def _env_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_path = pathlib.Path(os.environ.get("HERMES_HOME", "/opt/data")) / ".env"
    try:
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _twelve_search(query: str) -> list[dict[str, Any]]:
    api_key = _env_value("TWELVE_DATA_API_KEY")
    if not api_key or not query:
        return []
    params = urllib.parse.urlencode({"symbol": query, "outputsize": 20, "apikey": api_key})
    obj = _http_json(f"https://api.twelvedata.com/symbol_search?{params}")
    return obj.get("data", []) if obj.get("status") == "ok" else []


def _normalise_exchange(value: str) -> str:
    aliases = {"XETRA": "XETR", "FRANKFURT": "XFRA", "EURONEXT": "XAMS"}
    return aliases.get(value.upper(), value.upper())


def _auto_twelve_symbol(instrument: dict[str, Any]) -> str | None:
    """Resolve an exact exchange/currency listing from Twelve Data search metadata."""
    ticker = str(instrument.get("ticker") or "")
    query = str(instrument.get("provider_symbol_hint") or ticker.split("_", 1)[0])
    # Trading 212 venue suffixes are lowercase; remove only that suffix pattern,
    # then require Twelve Data search to confirm the exchange and currency.
    if query and query[-1:].islower() and query[:-1].isupper():
        query = query[:-1]
    expected_exchange = _normalise_exchange(str(instrument.get("exchange") or ""))
    expected_currency = str(instrument.get("currency") or "").upper()
    candidates = _twelve_search(query)
    for item in candidates:
        mic = str(item.get("mic_code") or item.get("exchange") or "").upper()
        currency = str(item.get("currency") or "").upper()
        if mic == expected_exchange and currency == expected_currency:
            symbol = str(item.get("symbol") or "").strip()
            if symbol:
                return f"{symbol}:{mic}"
    return None


def _cache_path(cache_dir: pathlib.Path, provider: str, symbol: str) -> pathlib.Path:
    key = hashlib.sha256(f"{provider}:{symbol}".encode()).hexdigest()[:24]
    return cache_dir / f"{provider}-{key}.json"


def _load_cache(path: pathlib.Path) -> list[dict[str, Any]] | None:
    try:
        obj = json.loads(path.read_text())
        if time.time() - float(obj["saved_at"]) <= CACHE_TTL_SECONDS:
            return obj["candles"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None


def _save_cache(path: pathlib.Path, candles: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"saved_at": time.time(), "candles": candles}, separators=(",", ":")))
    tmp.replace(path)


def fetch_twelve_data(symbol: str, days: int) -> list[dict[str, Any]]:
    api_key = _env_value("TWELVE_DATA_API_KEY")
    if not api_key:
        raise ValueError("TWELVE_DATA_API_KEY is not configured")
    symbol_name, separator, exchange = symbol.partition(":")
    query_values = {"symbol": symbol_name or symbol, "interval": "1day", "outputsize": max(days, 250), "apikey": api_key}
    if separator and exchange:
        query_values["exchange"] = exchange
    query = urllib.parse.urlencode(query_values)
    obj = _http_json(f"https://api.twelvedata.com/time_series?{query}")
    if obj.get("status") == "error" or "values" not in obj:
        raise ValueError(str(obj.get("message") or obj.get("code") or "Twelve Data returned no values"))
    out = []
    for item in obj["values"]:
        try:
            out.append({"date": str(item["datetime"])[:10], "open": float(item["open"]), "high": float(item["high"]), "low": float(item["low"]), "close": float(item["close"]), "volume": float(item.get("volume") or 0)})
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda x: x["date"])
    if len(out) < 30:
        raise ValueError(f"only {len(out)} valid Twelve Data candles")
    return out[-days:]


def fetch_yahoo(symbol: str, days: int) -> list[dict[str, Any]]:
    end = int(time.time())
    start = end - max(days * 2, 550) * 86400
    query = urllib.parse.urlencode({"period1": start, "period2": end, "interval": "1d", "events": "history", "includeAdjustedClose": "true"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='') }?{query}"
    obj = _http_json(url)
    result = obj["chart"]["result"]
    if not result:
        raise ValueError("Yahoo returned no data")
    result = result[0]
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    out = []
    for i, stamp in enumerate(timestamps):
        try:
            values = {key: quote[key][i] for key in ("open", "high", "low", "close", "volume")}
            if any(value is None for value in values.values()):
                continue
            out.append({"date": dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date().isoformat(), "open": float(values["open"]), "high": float(values["high"]), "low": float(values["low"]), "close": float(values["close"]), "volume": float(values["volume"])})
        except (KeyError, IndexError, TypeError, ValueError, OverflowError):
            continue
    if len(out) < 30:
        raise ValueError(f"only {len(out)} valid Yahoo candles")
    return out[-days:]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _atr(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(candles) <= period:
        return None
    trs = []
    for previous, current in zip(candles, candles[1:]):
        trs.append(max(current["high"] - current["low"], abs(current["high"] - previous["close"]), abs(current["low"] - previous["close"])))
    return _mean(trs[-period:])


def indicators(candles: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [x["close"] for x in candles]
    latest = closes[-1]
    def sma(period: int) -> float | None:
        return _mean(closes[-period:]) if len(closes) >= period else None
    gains, losses = [], []
    for a, b in zip(closes[-15:-1], closes[-14:]):
        change = b - a
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_loss = _mean(losses)
    rsi = 100.0 if avg_loss == 0 and gains else (100 - 100 / (1 + _mean(gains) / avg_loss) if avg_loss else None)
    atr = _atr(candles)
    def rounded(value: float | None, digits: int) -> float | None:
        return round(value, digits) if value is not None else None

    return {
        "last_close": round(latest, 8),
        "as_of": candles[-1]["date"],
        "bars": len(candles),
        "sma20": rounded(sma(20), 8),
        "sma50": rounded(sma(50), 8),
        "sma200": rounded(sma(200), 8),
        "rsi14": rounded(rsi, 4),
        "atr14": rounded(atr, 8),
        "atr14_pct": round(100 * atr / latest, 4) if atr and latest else None,
        "return20_pct": round(100 * (latest / closes[-21] - 1), 4) if len(closes) >= 21 else None,
        "return60_pct": round(100 * (latest / closes[-61] - 1), 4) if len(closes) >= 61 else None,
        "high20": round(max(x["high"] for x in candles[-20:]), 8) if len(candles) >= 20 else None,
        "low20": round(min(x["low"] for x in candles[-20:]), 8) if len(candles) >= 20 else None,
        "avg_volume20": round(_mean([x["volume"] for x in candles[-20:]]), 4) if len(candles) >= 20 else None,
    }


def analyze(instrument: dict[str, Any], cache_dir: pathlib.Path, days: int) -> dict[str, Any]:
    ticker = instrument.get("ticker")
    isin = instrument.get("isin")
    currency = instrument.get("currency")
    exchange = instrument.get("exchange")
    if not all(isinstance(x, str) and x.strip() for x in (ticker, isin, currency, exchange)):
        return {"status": "unresolved", "ticker": ticker, "error": "ticker, isin, currency, and exchange are required"}
    twelve_symbol = instrument.get("twelve_symbol") or _auto_twelve_symbol(instrument)
    providers = [("twelve_data", twelve_symbol, fetch_twelve_data), ("yahoo", instrument.get("yahoo_symbol"), fetch_yahoo)]
    errors = []
    for provider, symbol, fetcher in providers:
        if not symbol:
            errors.append(f"{provider}: no explicitly verified symbol")
            continue
        path = _cache_path(cache_dir, provider, symbol)
        candles = _load_cache(path)
        source = "cache" if candles else provider
        try:
            if candles is None:
                candles = fetcher(symbol, days)
                _save_cache(path, candles)
            latest = dt.date.fromisoformat(candles[-1]["date"])
            age = (dt.date.today() - latest).days
            if age > 7:
                raise ValueError(f"latest candle is {age} days old")
            return {"status": "ok", "ticker": ticker, "isin": isin, "currency": currency, "exchange": exchange, "provider": provider, "source": source, "symbol": symbol, "resolved_twelve_symbol": twelve_symbol, "latest_candle_age_days": age, "indicators": indicators(candles)}
        except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
            errors.append(f"{provider}: {exc}")
    return {"status": "unavailable", "ticker": ticker, "isin": isin, "currency": currency, "exchange": exchange, "resolved_twelve_symbol": twelve_symbol, "error": "; ".join(errors)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instruments", required=True, help="JSON array or path to a JSON array")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--cache-dir", default=os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "cache", "candles"))
    args = parser.parse_args()
    raw = pathlib.Path(args.instruments).read_text() if pathlib.Path(args.instruments).exists() else args.instruments
    instruments = json.loads(raw)
    if not isinstance(instruments, list):
        raise SystemExit("--instruments must be a JSON array")
    result = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "days": args.days, "provider_configuration": {"twelve_data_key_configured": bool(_env_value("TWELVE_DATA_API_KEY")), "twelve_data_key_source": "profile .env or process environment"}, "results": [analyze(item, pathlib.Path(args.cache_dir), args.days) for item in instruments]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
