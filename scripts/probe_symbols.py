#!/usr/bin/env python3
"""Probe Yahoo Chart metadata for candidate symbols to verify exact listing (summary only)."""
import json
import urllib.parse
import urllib.request
import time

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

def probe(symbol, *, timeout=18):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='')}?period1=0&period2=9999999999&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            obj = json.loads(r.read().decode("utf-8"))
        result = obj.get("chart", {}).get("result", [])
        if not result:
            return {"symbol": symbol, "status": "no_result"}
        meta = result[0].get("meta", {})
        q = result[0].get("indicators", {}).get("quote", [{}])[0]
        return {
            "symbol": meta.get("symbol"),
            "longName": meta.get("longName"),
            "shortName": meta.get("shortName"),
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
            "quote": {k: q.get(k) for k in ("open","high","low","close","volume") if k in q},
            "first_close": q.get("close", [None])[0],
        }
    except Exception as e:
        return {"symbol": symbol, "status": "error", "error": type(e).__name__}

if __name__ == "__main__":
    cands = ["VWCE.DE", "VUAA.DE", "CEBZ.DE", "IE00BK5BQT80", "IE00BFMXXD54", "IE000MAO75G5"]
    for s in cands:
        out = probe(s)
        print(json.dumps(out, sort_keys=True))
        time.sleep(1.2)
