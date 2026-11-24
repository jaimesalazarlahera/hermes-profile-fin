# Research quality gate — reference

Operational depth for the standing research-quality rule (embedded in `SKILL.md`'s Research-quality gate bullet). Apply to every research run of the T212 portfolio automation.

## 1. Junk page markers (drop, never retry)

Junk pages do not become readable on re-scrape, so they are classed as
**non-retryable failures** and removed from the research payload fed to the
selector. Detect from the scraped **content** (or, at search-result level,
from the title/URL heuristics below):

| Marker (case-insensitive) | Why it is junk |
|---|---|
| `relevance inspector` / `ignoreopen` / `skip to the content` | Vendor search-interface dashboard pages, not fund content |
| `connecting:` / `forwarded:` | Proxy/interstitial headers; the real factsheet usually follows the same URL, but the scraped view is a connection page |
| `lighthouse` / `ux-audit` / `chrome insp` | Chrome performance-audit popups pinned over the page |
| `javascript is required` / `next.js` / `__next` / `page render` | Server-side-render fail pages |
| `similarweb` / `fonts.googleapis` | Script-injection cards, no fund data |
| Short/error fragments: `404`, `nothing here`, `there's nothing here` | Broken or deleted pages |

At search-result level, drop rows whose **title is exactly the search query**
(the provider echoes the query as a placeholder title) and rows whose URL is a
truncated/empty path (e.g. `...//etf/eq`, `.../product//`). Count any page
whose **extracted content is under 200 characters** as low signal and drop it.

## 2. Extraction retry boundary

| Classify as | Action |
|---|---|
| Transient (429/408/425/5xx/timeout/network) per URL | Retry: 4 attempts total, delays 2s → 4s → 8s (cap 30s) |
| Junk / interstitial page | Drop. Never re-scrape |
| Permanent 4xx (401/403/404) or empty content | Drop; record in `extraction` status |

## 3. Status wording (determinism)

- Success: `succeeded`
- No usable content: `no usable content (<reasons>)` where each reason is
  `url: <junk/interstitial|nocompontent returned|transient error>` (bounded to ~200 chars)
- Reason strings must come from the extraction step, never inferred by the
  operator. They become the report's Research section text when the run is
  delivered.

## 4. Target rotation (quality-ranked selection)

Rank extraction targets: structured, readable sources rank first:
`factsheet`, `snapshotresearch`, `tipranks`, `stocktrademastery`,
`lightyear`, `perplexity`, `ishares`, `nl.vanguard`, `vnif`, `knight`.
Then take the top **6** URLs (non-junk, URL-unique). Fire them in one
extraction batch; fall back silently when a batch returns fewer usable items.

## 5. Verification recipe (per run)

```bash
# 1. research JSON has no junk markers in extracted/search_results
python - <<'PY'
import json, re
d = json.load(open('/tmp/r4.json'))
ruin = re.compile(r'relevance inspector|connecting:|forwarded:|lighthouse|skip to the content', re.I)
print('extracted clean:', all(not ruin.search(str(x.get('content',''))) for x in d['extracted']))
print('search clean:', all(not ruin.search(str(x.get('title',''))) for x in d['search_results']))
PY
# 2. content length check
python - <<'PY'
import json
d = json.load(open('/tmp/r4.json'))
print('usable items:', [(e.get('url','?')[:35], len(e.get('content',''))) for e in d['extracted']])
PY
```