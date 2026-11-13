# Free Candle Data Workflow

Use this reference when a Trading 212 run needs OHLCV candles or technical indicators.

## Provider order

1. **Twelve Data** when `TWELVE_DATA_API_KEY` is present in the active profile `.env`.
2. **Yahoo Finance chart data** as the no-key fallback.
3. If both fail, mark technical data unavailable and continue only with the other research and risk controls.

A fallback result does not prove that the primary provider worked. Report the actual provider, latest candle date, bar count, and provider failures separately. A key-presence check is not a data-availability check: Twelve Data symbol search can find an ETF while its `time_series` request still returns a listing/plan error or a rate limit. Test the actual OHLCV request and distinguish `key_configured`, `symbol_unavailable`, and `rate_limited`. Treat failures as per-symbol: record the symbol and continue through the batch.

Retry only transient `408`, `425`, `429`, `5xx`, and network failures with bounded exponential backoff, honoring `Retry-After` when present; do not retry permanent `4xx` errors. Keep retries inside the shared HTTP layer so every provider request gets the same policy.

## Profile secret setup

Keep the key in the active profile, never in `config.yaml`, the cron prompt, a JSON input file, or a report:

```bash
read -rsp 'Twelve Data API key: ' key
printf '\nTWELVE_DATA_API_KEY=%s\n' "$key" >> "$HERMES_HOME/.env"
unset key
```

The candle collector reads `TWELVE_DATA_API_KEY` from the process environment or the active profile `.env`, with `$HERMES_HOME/.env` authoritative for a profile cron run. Do not use a separate shell-only probe to conclude that the key is missing; rely on the collector's JSON `provider_configuration.twelve_data_key_configured` field and the actual request result.

## Collector

The reusable collector is:

```text
$HERMES_HOME/scripts/candle_analysis.py
```

Store per-run input under `$HERMES_HOME/cache/scratch/` and reusable candle cache under `$HERMES_HOME/cache/candles/`:

```bash
python "$HERMES_HOME/scripts/candle_analysis.py" \
  --instruments "$HERMES_HOME/cache/scratch/t212-candle-input.json" \
  --days 250
```

Each input object must include the exact Trading 212 ticker, ISIN, and currency. Exchange is preferred when Trading 212 supplies it; account/order records may omit exchange, in which case the collector must resolve a provider venue from metadata/search and enforce a currency-compatible listing rather than guessing a suffix:

```json
{
  "ticker": "<Trading 212 ticker>",
  "isin": "<ISIN>",
  "currency": "EUR",
  "exchange": "<optional exchange>",
  "twelve_symbol": "<optional verified symbol:MIC>",
  "yahoo_symbol": "<optional verified Yahoo symbol>"
}
```

Do not manually guess or substitute a similarly named ETF. Verify the listing by ISIN, exchange, currency, and instrument type first. When `twelve_symbol` is absent, the collector uses Twelve Data symbol search and filters by the exact exchange MIC and currency, then records `resolved_twelve_symbol`. Symbol-search output alone is not success: verify that the historical time-series endpoint returns parseable rows. For Twelve Data, an exchange-qualified symbol may require separate `symbol` and `exchange` query fields.

## Validation gates

Reject a provider response when it is not parseable OHLCV, has fewer than 30 valid bars, has a stale latest date, or cannot be tied to the exact listing. Do not turn missing data into a neutral signal. Technical indicators support ranking, staging, and volatility-aware risk; they are not automatic trade triggers.

## Order safety around data failures

Data-provider failure does not justify new speculative orders. Continue existing-position and pending-order risk management using available evidence, and state the technical-data gap in Telegram and the final report.
