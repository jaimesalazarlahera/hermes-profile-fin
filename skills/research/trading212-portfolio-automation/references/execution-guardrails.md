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
