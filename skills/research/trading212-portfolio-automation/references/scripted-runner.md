# Scripted runner workflow

Use this recipe when converting a prompt-driven Trading 212 cron job into a deterministic runner with one bounded selector call.

## Components

Keep four layers separate:

1. A research command emits JSON after current web search and extraction. It gathers evidence; it does not choose tickers or place orders.
2. A selector adapter reads the runner prompt on stdin, calls Hermes once, and emits only the candidate JSON object. Instruct it not to use tools or browse.
3. The Python runner owns MCP reads, the current EUR ETF universe, exact identity validation, sizing, duplicate gates, pre-write refreshes, order writes, readbacks, rendering, and delivery.
4. A cron wrapper invokes the runner with absolute interpreter and script paths and reads the environment from the active Trading 212 config.

## Selector contract

The selector should receive:

- current account cash, positions, and pending orders;
- a bounded current research JSON payload;
- an exact current instrument universe containing ticker, ISIN, name, type, and currency.

Require exactly:

```json
{"candidates":[{"ticker":"...","isin":"...","currency":"EUR","exchange":"...","price":0.0,"allocation_pct":0.0,"rationale":"..."}]}
```

Reject malformed JSON, unknown keys, invented tickers/ISINs, non-EUR instruments, invalid prices, and allocations outside `(0, 1]`. The selector never authorizes an order.

## Hermes selector invocation

For a small standalone LLM adapter, use a bounded one-shot invocation:

```bash
/opt/hermes/bin/hermes chat \
  --query-file - --oneshot -Q --format text --max-turns 10
```

Set `HERMES_HOME` and `HOME` to the active profile, prepend `/opt/hermes/bin` and `/opt/hermes/.venv/bin` to `PATH`, and run the adapter from the profile directory itself (the CWD must be the profile root for `hermes chat` to resolve skills/gateway). Feed the prompt on stdin, and keep the prompt compact: account state (<3000 chars) + research (<6000 chars). The model can run out of steps calling tools and exit non-zero; the adapter must fall back to extracting the first JSON object containing `candidates` rather than treating that as a hard failure.

## Cron migration

Place the wrapper under the active profile's `scripts/` directory. Hermes cron expects the script argument relative to that directory, not an absolute path:

```bash
hermes cron edit <job-id> \
  --script t212_portfolio_automation_cron.py \
  --no-agent
```

With `--no-agent`, stdout is delivered verbatim, so the runner must print only the final deterministic report. Do not leave a prompt-driven fallback enabled on the same job.

## Verification gates

1. Run the research command and validate its JSON shape.
2. Run the selector adapter with a fixture prompt and validate its JSON shape.
3. Exercise the MCP stdio handshake and one real read-only account collection.
4. Run the complete wrapper in dry-run mode against the demo account.
5. Confirm duplicate pending orders are preserved and no write tool is called.
6. Only then migrate the scheduled job; use the CLI and read the job back afterward.

## Pitfalls

- Resolve the exact instrument universe before the selector call; web research commonly contains fund names but not the exchange-specific Trading 212 ticker, so a free-form model can invent an attractive but untradeable symbol.
- Decode Trading 212 list responses as a stream of JSON values; the MCP server can return concatenated objects or an empty content block for an empty list.
- Use absolute interpreter paths inside cron wrappers; cron PATH differs from an interactive shell and can select a Python without the MCP/web dependencies.
- Keep the runner dry-run by default until the user authorizes execution; after authorization, pass `--execute` explicitly in the cron wrapper. The configured `ENVIRONMENT` selects demo or live independently of execution, and live still requires a separate explicit approval gate because a no-agent cron job has no LLM turn available to catch unsafe assumptions.
- Re-fetch cash, positions, and pending orders before each order even after planning; fills and blocked funds can invalidate the previous plan.
- Do not parallelize metadata calls against a rate-limited account; fetch the universe once, reuse it for validation, and let the provider's bounded retry policy handle transient responses.
