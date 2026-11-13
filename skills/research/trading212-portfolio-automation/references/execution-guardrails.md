# Execution guardrails

## Default staged allocation

For a new EUR demo portfolio when the user has not supplied a different risk budget:

| Sleeve | Target | First tranche | Rule |
|---|---:|---:|---|
| Global equity UCITS ETF | 70% | 50% of sleeve | Use a broad accumulating fund such as the verified EUR listing of VWCE. |
| Broad US equity UCITS ETF | 20% | 50% of sleeve | Use the verified EUR listing of VUAA only as a deliberate US tilt. |
| Cash | 10% | Always retained | Do not commit this reserve to pending orders. |

The default is a starting point, not a claim that this allocation is suitable for every user. If the user specifies a different risk budget, use theirs.

## Order decision table

| Situation | Action |
|---|---|
| Market closed or quote is delayed | Use a GTC limit order near, but not above, the latest reliable reference; label it pending. |
| User explicitly requests immediate execution | Confirm market-order risk and use a market order only if the account, ticker, and cash checks pass. |
| Matching pending order exists | Do not duplicate; verify and report the existing order. |
| Cash is blocked by pending orders | Subtract blocked cash before sizing the next tranche. |
| Instrument search returns several listings | Select by ISIN plus EUR currency and verify the name; do not guess from the first result. |
| Earnings or major event is imminent for a single stock | Avoid opening the concentrated position; prefer diversified exposure or wait. |
| Order is NEW/PENDING | Do not call it filled or include it in invested positions. |
| Order is filled | Fetch the position, then add one protective exit if the approved policy requires it. |

## Recurring-monitoring rules

Every run should fetch, in order: account info, cash, portfolio summary, open positions, pending orders, and recent activity. Reconcile these before deciding whether to place, cancel, or modify anything. After every write, read the exact target back. Keep the final delivery short and include what remains pending.

## Trading 212 API rate limits

The free-tier Pro Trading 212 account Rate-limits aggressively (roughly 15–30 requests per minute). Pipeline command counts for a typical low-frequency run:

| Step | Calls | Reason |
|---|---|---|
| Account collection (`collect_state`) | 5 | account_info, account_cash, open_positions, orders, recent_activity |
| Each `execute_orders` pass | 7 | preflight orders, preflight positions, cash refresh, place order, order readback, orders refresh, cash refresh |

The MCP wrapper (`_mcp_call`) is the correct place for shared retry/back-off. Every Trading 212 API call should be wrapped as follows, and the pipeline must survive three consecutive 429s before failing:

```python
max_attempts = 4
base_delay = 2.0  # seconds
for attempt in range(1, max_attempts + 1):
    try:
        response = await session.call_tool(name, arguments or {})
        # ... parse ...
    except Exception as exc:
        if attempt < max_attempts:
            wait = min(30.0, base_delay * (2 ** (attempt - 1)))
            print(f"  [t212] API call '{name}' failed ({exc}); retry {attempt}/{max_attempts} in {wait:.1f}s", file=sys.stderr)
            await asyncio.sleep(wait)
        else:
            print(f"  [t212] API call '{name}' failed after {max_attempts} attempts: {exc}", file=sys.stderr)
            raise
```

Rules of thumb for extra calls that are true sources of rate limits:

1. **Each pending order triggers ~7 sequential MCP calls** (preflight orders, preflight positions, cash refresh, place, order readback, orders refresh, cash refresh). Three pending orders = ~21 calls. The free-tier API limit is ~30 req/min, so this causes 429 rate-limit retries. Split the pipeline into two stages: (a) account collection — one pass, all read-only inventory; (b) order execution — only place + fetch_order per new candidate. Fetch account cash/positions/orders once at the start of the run and cache in memory; do not re-read them inside the write loop (their only mutating callers are the pipeline itself, which writes once). Example optimized per-order cost: place_limit_order + fetch_order (2 calls), no preflight or post-write refresh.

2. **Each pending order triggers ~7 sequential MCP calls** (preflight orders, preflight positions, cash refresh, place, order readback, orders refresh, cash refresh). Three pending orders = ~21 calls. This is the default implementation pattern — do not accept it without analysis. Before writing, ask: which of these calls read-only state that the write itself changes? Only the place and the readback are required; the pending-orders/positions/cash refreshes are redundant when the run has already fetched full account state once at the start. If an order fails, re-read affected endpoints, but do not per-order pre-flight unless necessary.
