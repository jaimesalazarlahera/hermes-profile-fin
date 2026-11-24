# Order-level broker rejection flow

## Pre-order preflight (execute_orders)

Before any buy order reaches `place_limit_order`, compute the instrument's
minimum tradable lot from the account instrument catalogue record
(`minTradeQuantity` / `min_trade_quantity`) and reject anything below it
before the broker ever sees it:

```text
min_lot = instrument_min_trade_quantity(catalog_records, order.ticker)
if min_lot is not None and order.quantity < min_lot:
    results.append({ticker, status: "REJECTED_BY_BROKER",
                    reason: f"below minimum tradable lot ({min_lot} shares)",
                    quantity, limit_price})
    continue   # no broker call for this order
```

This gate converts a never-contracted broker failure into a deterministic
row that is carried into the report's **Next actions**.

Catalogue entry with `minTradeQuantity` unset is *unknown*, not *zero*:
do not hard-block; log the miss and let the broker's rule layer be the
fallback (e.g. IWLEq_EQ `must trade at least 0.09900500` in the LIVE
account).

## Retry boundary

- Retry only transient failures: 408/425/429/500/502/503/504, `timed out`/
  `timeout`, non-JSON transport blips. Bounded: 4 attempts, exponential
  backoff 2s → 4s → 8s (max 30 s).
- A permanent 4xx payload/broker-rule validation is never retried: `price
  too far`, `instrument can not be traded`, unknown ticker, malformed
  broker response. When retries are exhausted the order is recorded
  deterministically as `REJECTED_BY_BROKER` (or `ERROR`), preserving
  `{ticker, status, reason, quantity, limit_price}`, and the run continues
  with the remaining orders.

## Carry-over into the report

- Order-level `REJECTED_BY_BROKER`/`ERROR` result rows are merged into
  `plan.rejections` (dedup on ticker + reason) by `_carry_over_order_rejections`;
  the template renders `next_actions = plan.rejections[:5]`, so broker
  rejections are explained in **Next actions**, not only as muted rows under
  **Orders this run**.
- Uniform result shape: result `ticker` falls back to request.ticker;
  result `reason` falls back to request.arguments limit/target price.
- Keep every one of these writes verified: a 4xx with no order id is a
  rejection row — never misreport it as a NEW order or as a run failure.