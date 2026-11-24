# Order planning catalogue gate

Cross-reference every candidate against the environment-keyed Trading 212 instrument catalogue cache
(`$HERMES_HOME/cache/trading212/instruments-{demo,live}.json`) before sizing. A candidate may be ordered
only when the catalogue yields exactly one tradable record.

Hard gate rule — reject deterministically, no broker call:
1. Match the candidate's exact ticker OR exact ISIN against catalogue records.
2. Require exactly one match.
3. Require the matched record to be tradable in this account: type ETF or STOCK, EUR settlement.

Every mismatch becomes a deterministic plan rejection (`<ticker>: <reason>`):
- no record: `<ticker>: no instrument catalogue record (not tradable in this account)`
- more than one record: `<ticker>: N instrument catalogue records match (ambiguous, rejected)`
- non-ETF/STOCK: `<ticker>: catalogue record type '<TYPE>' is not an orderable equity/ETF`
- non-EUR: `<ticker>: catalogue record is <CCY>, not EUR`

An ambiguous catalogue (duplicate ticker, or the same ISIN listed under two venues) is treated as a
data-quality defect: re-read the cache, force-refresh, and suspect the source listing before re-planning.

Re-check triggers: unknown tickers from the selector; broker rejections of previously catalogue-matched
instruments; any catalogue refresh (7-day (weekly) TTL). When the catalogue cannot be loaded, do not place new orders.