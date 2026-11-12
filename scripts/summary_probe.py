import json, re

text = open("/opt/data/profiles/poe/cache/scratch/symbols_probe.json").read()
blocks = re.split(r"\n(?=\{)", text)
for b in blocks:
    b = b.lstrip()
    try:
        o = json.loads(b)
    except Exception:
        # take everything up to the closing of the first object is risky; try lenient
        continue
    # Only print summary if this is a summary object (no 'quote' list with opens)
    def has_list_value(obj, key):
        v = obj.get(key)
        return isinstance(v, list)
    summary = {
        "symbol": o.get("symbol"),
        "longName": o.get("longName"),
        "shortName": o.get("shortName"),
        "currency": o.get("currency"),
        "exchange": o.get("exchange"),
    }
    # determine provider-metadata keys present
    meta_keys = [k for k in o.keys() if k in ("symbol","longName","shortName","currency","exchange","sector","marketCap","currentPrice")]
    print(json.dumps(summary, indent=2))
    print("meta_keys:", meta_keys)
    print("---")
