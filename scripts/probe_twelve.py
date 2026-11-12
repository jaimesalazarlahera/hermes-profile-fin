#!/usr/bin/env python3
"""Probe Twelve Data time_series for candidate symbols (to select verified twelve_symbol)."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")

def probe(symbol, *, timeout=25):
    if not API_KEY:
        return {"symbol": symbol, "status": "no_key"}
    url = f"https://api.twelvedata.com/time_series?symbol={urllib.parse.quote(symbol)}&interval=1day&outputsize=250&apikey={API_KEY}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            obj = json.loads(r.read().decode("utf-8"))
        if obj.get("status") == "ok":
            vals = obj.get("values", [])
            return {
                "symbol_in": symbol,
                "status": "ok",
                "name": obj.get("name"),
                "currency": obj.get("currency"),
                "count": len(vals),
                "latest_date": vals[0].get("datetime") if vals else None,
                "latest_close": vals[0].get("close") if vals else None,
            }
        return {"symbol_in": symbol, "status": obj.get("status"), "message": obj.get("message")}
    except Exception as e:
        return {"symbol_in": symbol, "status": "error", "error": type(e).__name__}

if __name__ == "__main__":
    cands = ["VWCE", "VUAA", "CEBZ", "VWCE.DE", "VUAA.DE", "CEBZ.DE", "IE00BK5BQT80", "IE00BFMXXD54", "IE000MAO75G5"]
    for s in cands:
        print(json.dumps(probe(s), sort_keys=True))
