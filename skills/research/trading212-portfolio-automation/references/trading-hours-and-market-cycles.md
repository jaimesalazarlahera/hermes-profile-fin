# Trading hours & market-cycles facts (EUR-settled accounts)

## Venue hours (verified against Trading 212 exchange schedules, live)

- **Deutsche Börse Xetra** (VGWLd_EQ, CEBZd_EQ, APCd_EQ, TL0d_EQ, ...): **08:00–16:30 UTC**, Mon–Fri
- **Euronext Amsterdam** (VWRLa_EQ): **08:00–16:30 UTC**, Mon–Fri
- All EUR listings in this account close at **16:30 UTC**.

## What this means for the automation

- The `*/30 8-18 * * 1-5` UTC cadence is a **choice** (European window + a 2h processing buffer), not a broker limit. Everything this account can trade ends at 16:30 UTC; runs 17:00–18:30 are post-close reconciliation only.
- **No instrument in this account has extended hours.** US extended-hours trading applies to USD listings; this API executes only in the account's primary currency (EUR), so the EUR line of US tickers (APCd_EQ, TL0d_EQ on Xetra) has no after-hours session.
- **Stops/TP on a full-position bracket survive the close**: GTC sell orders stay on the book overnight and resume at the next open. Protection resumes automatically — no overnight monitoring is required for execution.
- **The real stop-loss risk is a gap at open**: overnight/US-session news can gap the EUR line at 08:00, so a stop-market can fill well below its stop. This is inherent to stop orders on non-24h venues; monitoring cannot close it.

## Cadence reference

- Short-term bracket-exit cron (no native OCO): `*/30 8-18 * * 1-5` in UTC — every 30 minutes on weekdays during the European window.
- Run frequency decision: monitor during the liquid window for fills/cancellations; runs after 16:30 serve reconciliation and next-day watch only. Increase frequency only if the strategy requires same-day closes or intra-session rebalancing.
