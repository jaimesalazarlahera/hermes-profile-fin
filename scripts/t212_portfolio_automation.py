#!/usr/bin/env python3
"""Guarded Trading 212 portfolio runner.

The policy functions in this module are deterministic and intentionally separate
from the MCP, research, and LLM adapters. The default CLI mode is dry-run.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import os
import subprocess
import sys
import asyncio
from contextlib import asynccontextmanager, aclosing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import types

from mcp.client.session import ClientSession
from mcp.types import Implementation


class ProposalError(ValueError):
    """The LLM returned a proposal outside the required JSON contract."""


class UnknownWriteState(RuntimeError):
    """An order write did not return a verifiable order object."""


@dataclass(frozen=True)
class Policy:
    reserve_pct: float = 0.10
    first_tranche_pct: float = 0.50
    min_order_value: float = 1.0


@dataclass(frozen=True)
class Candidate:
    ticker: str
    isin: str
    currency: str
    exchange: str
    price: float
    allocation_pct: float
    rationale: str
    stop_loss_pct: float | None = None


@dataclass(frozen=True)
class PlannedOrder:
    ticker: str
    isin: str
    quantity: float
    limit_price: float
    notional: float
    rationale: str


@dataclass(frozen=True)
class OrderPlan:
    orders: list[PlannedOrder]
    rejections: list[str]
    remaining_cash: float


def configured_environment() -> str:
    configured = os.environ.get("T212_ENVIRONMENT", "").strip()
    if configured:
        return configured
    config_path = Path(os.environ.get("HERMES_HOME", "/opt/data")) / "config.yaml"
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    for line in text.splitlines():
        if line.strip().startswith("ENVIRONMENT:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return "unknown"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ProposalError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ProposalError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ProposalError(f"{field} must be finite")
    return result


def parse_llm_proposal(raw: str) -> list[Candidate]:
    """Parse the narrow candidate contract returned by the one LLM call."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProposalError("LLM output is not JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"candidates"}:
        raise ProposalError("LLM output must contain only a candidates array")
    entries = payload["candidates"]
    if not isinstance(entries, list):
        raise ProposalError("candidates must be an array")

    result: list[Candidate] = []
    required = {"ticker", "isin", "currency", "exchange", "price", "allocation_pct", "rationale"}
    allowed = required | {"stop_loss_pct"}
    for index, item in enumerate(entries):
        if not isinstance(item, dict) or not required.issubset(item) or set(item) - allowed:
            raise ProposalError(f"candidate {index} has an invalid schema")
        ticker, isin, currency, exchange, rationale = (
            _text(item["ticker"]), _text(item["isin"]), _text(item["currency"]).upper(),
            _text(item["exchange"]).upper(), _text(item["rationale"]),
        )
        if not all((ticker, isin, currency, exchange, rationale)):
            raise ProposalError(f"candidate {index} has an empty required field")
        price = _number(item["price"], f"candidate {index}.price")
        allocation = _number(item["allocation_pct"], f"candidate {index}.allocation_pct")
        if price <= 0 or not 0 < allocation <= 1:
            raise ProposalError(f"candidate {index} has invalid price or allocation")
        stop = item.get("stop_loss_pct")
        stop_value = None if stop is None else _number(stop, f"candidate {index}.stop_loss_pct")
        if stop_value is not None and not 0 < stop_value < 1:
            raise ProposalError(f"candidate {index}.stop_loss_pct must be between 0 and 1")
        result.append(Candidate(ticker, isin, currency, exchange, price, allocation, rationale, stop_value))
    return result


def _identity_matches(candidate: Candidate, record: dict[str, Any]) -> bool:
    ticker = _text(record.get("ticker"))
    isin = _text(record.get("isin"))
    return bool(ticker == candidate.ticker or (isin and isin == candidate.isin))


def _is_distributing_ticker(ticker: str) -> bool:
    """Return True if the ticker is a distributing instrument, False if accumulating."""
    # Trading 212 ticker suffixes:
    #   d_EQ / l_EQ  = distributing (distributing / distributing-low)
    #   m_EQ / a_EQ  = accumulating (monthly / accumulating)
    # The suffix encodes the distribution policy; we only trade distributing tickers.
    upper = ticker.upper()
    if not upper.endswith("_EQ"):
        return False
    suffix = upper[:-len("_EQ")]
    # The character before _EQ encodes the distribution policy:
    #   'd' or 'l' = distributing, 'm' or 'a' = accumulating
    if not suffix:
        return False
    return suffix[-1] in ("D", "L")


def build_order_plan(
    *,
    free_cash: float,
    positions: Iterable[dict[str, Any]],
    pending_orders: Iterable[dict[str, Any]],
    candidates: Iterable[Candidate],
    policy: Policy,
) -> OrderPlan:
    """Build buy orders without performing any external writes."""
    cash = _number(free_cash, "free_cash")
    if cash < 0:
        raise ValueError("free_cash cannot be negative")
    position_records = list(positions)
    pending_records = list(pending_orders)
    remaining = cash * (1 - policy.reserve_pct)
    orders: list[PlannedOrder] = []
    rejections: list[str] = []

    for candidate in candidates:
        if _text(candidate.currency).upper() != "EUR":
            rejections.append(f"{candidate.ticker}: non-EUR candidate")
            continue
        if not _is_distributing_ticker(candidate.ticker):
            rejections.append(f"{candidate.ticker}: accumulating (not distributing) - filtered out")
            continue
        if any(_identity_matches(candidate, record) for record in position_records):
            rejections.append(f"{candidate.ticker}: duplicate exposure (position)")
            continue
        if any(_identity_matches(candidate, record) for record in pending_records):
            rejections.append(f"{candidate.ticker}: duplicate exposure (pending order)")
            continue
        if candidate.price <= 0 or not 0 < candidate.allocation_pct <= 1:
            rejections.append(f"{candidate.ticker}: invalid price or allocation")
            continue

        requested = cash * (1 - policy.reserve_pct) * candidate.allocation_pct
        tranche_cap = cash * (1 - policy.reserve_pct) * policy.first_tranche_pct
        notional = min(requested, tranche_cap, remaining)
        quantity = math.floor(notional / candidate.price * 10000) / 10000
        notional = round(quantity * candidate.price, 8)
        if quantity <= 0 or notional < policy.min_order_value:
            rejections.append(f"{candidate.ticker}: below minimum order value or reserve")
            continue
        orders.append(PlannedOrder(candidate.ticker, candidate.isin, quantity, candidate.price, notional, candidate.rationale))
        remaining = round(remaining - notional, 8)
        pending_records.append({"ticker": candidate.ticker, "isin": candidate.isin, "quantity": quantity})
    return OrderPlan(orders, rejections, remaining)


def validate_instrument(candidate: Candidate, matches: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return the exact Trading 212 listing matching identity and currency.

    Flexible matching: prefer exact ISIN, then exact ticker, then partial ticker
    (e.g. 'VWCE' matches 'VWCE.DE'). Raises ProposalError if no unique instrument
    is found.
    """
    exact_isin = []
    partial_ticker = []
    for item in matches:
        item_exchange = _text(item.get("exchange", item.get("exchangeCode"))).upper()
        exchange_matches = not item_exchange or item_exchange == candidate.exchange
        item_isin = _text(item.get("isin"))
        item_ticker = _text(item.get("ticker")).upper()
        isin_match = item_isin == candidate.isin
        ticker_match = (_text(item.get("ticker")) == candidate.ticker or
                        candidate.ticker.upper() in item_ticker or
                        item_ticker.startswith(candidate.ticker.upper()))
        if isin_match and exchange_matches and _text(item.get("currencyCode", item.get("currency"))).upper() == candidate.currency:
            exact_isin.append(item)
        elif ticker_match and exchange_matches:
            partial_ticker.append(item)
    if len(exact_isin) == 1:
        return exact_isin[0]
    if len(partial_ticker) == 1:
        return partial_ticker[0]
    if len(exact_isin) > 1:
        raise ProposalError(f"{candidate.ticker}: multiple instruments match ISIN {candidate.isin}, got {len(exact_isin)}")
    if len(partial_ticker) > 1:
        raise ProposalError(f"{candidate.ticker}: multiple instruments match ticker '{candidate.ticker}', got {len(partial_ticker)}")
    raise ProposalError(f"{candidate.ticker}: expected exactly one instrument match (ISIN or ticker), got {len(exact_isin) + len(partial_ticker)}")


def run_research(command: str) -> Any:
    completed = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProposalError("research command did not emit JSON") from exc


def build_llm_prompt(state: dict[str, Any], research: Any, existing_tickers: set[str]) -> str:
    contract = {
        "candidates": [{
            "ticker": "exact Trading 212 ticker",
            "isin": "exact ISIN",
            "currency": "EUR",
            "exchange": "exact exchange code",
            "price": 0.0,
            "allocation_pct": 0.0,
            "rationale": "brief evidence-based reason",
        }]
    }
    research_payload = json.dumps(research, separators=(',', ':'), default=str)
    # Truncate account state and research to compact subsets to keep the prompt within the model's context
    # and reduce timeout risk on the LLM selector call.
    state_payload = json.dumps(state, separators=(',', ':'), default=str)
    if len(state_payload) > 8000:
        state_payload = state_payload[:8000]
    if len(research_payload) > 6000:
        research_payload = research_payload[:6000]
    # Truncate existing tickers list to a smaller, more focused subset for the prompt
    existing_sorted = sorted(existing_tickers)
    if len(existing_sorted) > 40:
        existing_sorted = existing_sorted[:40]
    existing_str = json.dumps(existing_sorted, separators=(',', ':'))
    return (
        "You are a constrained JSON selector. Do not call tools, browse, research, or explain your work. "
        "Choose which tickers to trade from the following two sources:\n"
        "  SOURCE 1 (guaranteed tradeable): open positions and pending orders in your Trading 212 account.\n"
        "  SOURCE 2 (research candidates): new tickers from web_search + news/trends analysis.\n"
        "Only select tickers that appear in the SOURCES below. Do not invent tickers or use symbols from memory. "
        "Never choose leverage, inverse, CFD, short, or options products. "
        "Return JSON only, with exactly this schema; allocation_pct is a fraction of the first staged tranche. Constraints: price MUST be a number > 0; allocation_pct MUST be a number > 0; only select tickers from SOURCE 1 or SOURCE 2; if you cannot produce a candidate, return {'candidates': []}."
        f"SCHEMA={json.dumps(contract, separators=(',', ':'))}\n"
        f"SOURCE 1 (existing positions + pending orders in your Trading 212 account):\n{existing_str}\n"
        f"SOURCE 2 (research candidates):\n{research}"

    )


def call_llm(prompt: str, command: str, max_attempts: int = 4, base_delay: float = 5.0) -> list[Candidate]:
    """Call the LLM selector with retry/back-off for slow or transient failures.

    Trading 212's free-tier LLM selector (Nous API) can be slow under load.
    Retry with exponential back-off (5s, 10s, 20s) instead of failing on
    the first timeout.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            completed = subprocess.run(
                command, shell=True, input=prompt, check=False,
                capture_output=True, text=True, timeout=600,
            )
            if completed.returncode:
                detail = completed.stderr.strip() or completed.stdout.strip() or 'unknown selector error'
                raise ProposalError(f"LLM command failed: {detail[-1000:]}")
            return parse_llm_proposal(completed.stdout)
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout or exc.stderr or "<no partial selector output>"
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", errors="replace")
            print(f"  [t212] LLM selector timed out (attempt {attempt}/{max_attempts})", file=sys.stderr)
            if attempt < max_attempts:
                wait = base_delay * (2 ** (attempt - 1))
                wait = min(wait, 30.0)
                print(f"  [t212] Retrying in {wait:.1f}s...", file=sys.stderr)
                import time
                time.sleep(wait)
        except ProposalError as exc:
            if attempt < max_attempts:
                wait = base_delay * (2 ** (attempt - 1))
                wait = min(wait, 30.0)
                print(f"  [t212] LLM proposal error (attempt {attempt}/{max_attempts}): {exc}; retrying in {wait:.1f}s", file=sys.stderr)
                import time
                time.sleep(wait)
            else:
                raise
def _decode_json_stream(text: str) -> Any:
    decoder = json.JSONDecoder()
    index = 0
    values = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        value, end = decoder.raw_decode(text, index)
        values.append(value)
        index = end
    if len(values) == 1:
        return values[0]
    return values


async def _mcp_call(session: Any, name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Call an MCP tool on the Trading 212 server with retry/back-off on rate limits.

    Trading 212's free API rate-limits aggressively (typically ~15-30 req/min).
    The MCP server propagates HTTP 429 responses as tool-call failures, which
    currently crashes the whole pipeline. This wrapper retries with exponential
    back-off for a bounded number of attempts, then fails loudly.
    """
    max_attempts = 4
    base_delay = 2.0  # seconds
    for attempt in range(1, max_attempts + 1):
        try:
            response = await session.call_tool(name, arguments or {})
            text = "".join(block.text for block in response.content if hasattr(block, "text")).strip()
            if not text and name in {"fetch_all_open_positions", "fetch_all_orders", "search_instrument", "fetch_recent_activity"}:
                return []
            try:
                return _decode_json_stream(text)
            except (json.JSONDecodeError, ValueError) as exc:
                raise UnknownWriteState(f"{name} returned non-JSON data") from exc
        except Exception as exc:
            # Trading 212 API rate-limits (429) surface as MCP tool-call failures
            # Retry only transient transport/rate-limit/server failures. A 4xx
            # validation response is permanent for this payload and must fail
            # immediately instead of submitting the same invalid order four times.
            error_text = str(exc)
            retryable = any(token in error_text for token in ("408", "425", "429", "500", "502", "503", "504", "timed out", "timeout"))
            if attempt < max_attempts and retryable:
                # Exponential back-off: 2s, 4s, 8s
                wait = base_delay * (2 ** (attempt - 1))
                wait = min(wait, 30.0)  # Cap at 30s
                print(f"  [t212] API call '{name}' failed ({exc}); retry {attempt}/{max_attempts} in {wait:.1f}s", file=sys.stderr)
                await asyncio.sleep(wait)
            else:
                print(f"  [t212] API call '{name}' failed after {attempt} attempt(s): {exc}", file=sys.stderr)
                raise


async def collect_state(session: Any) -> dict[str, Any]:
    values = {}
    for name, args in (
        ("fetch_account_info", {}), ("fetch_account_cash", {}),
        ("fetch_all_open_positions", {}), ("fetch_all_orders", {}),
        ("fetch_recent_activity", {"limit": 20}),
    ):
        values[name] = await _mcp_call(session, name, args)
    return values


async def execute_orders(session: Any, plan: OrderPlan, *, execute: bool) -> list[dict[str, Any]]:
    results = []
    for order in plan.orders:
        if not execute:
            results.append({"ticker": order.ticker, "status": "DRY_RUN", "quantity": order.quantity})
            continue
        # Single endpoint call to place the order
        response = await _mcp_call(session, "place_limit_order", {
            "ticker": order.ticker, "quantity": order.quantity,
            "limit_price": order.limit_price, "time_validity": "GOOD_TILL_CANCEL",
        })
        # Read back the order to verify it was placed
        readback = await _mcp_call(session, "fetch_order", {"order_id": int(response["id"])})
        results.append({"request": asdict(order), "response": response, "readback": readback})
    return results


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        if value.get("ticker"):
            return [value]
        for key in ("items", "positions", "orders", "activity"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
    return []


CATALOG_TTL_SECONDS = 24 * 60 * 60
CATALOG_MAX_STALE_SECONDS = 72 * 60 * 60


def _catalog_path(home: Path, environment: str) -> Path:
    safe_environment = "live" if environment.lower() == "live" else "demo"
    return home / "cache" / "trading212" / f"instruments-{safe_environment}.json"


def _catalog_records(value: Any) -> list[dict[str, Any]]:
    records = _records(value)
    return [record for record in records if _text(record.get("ticker")) and _text(record.get("isin"))]


def _read_catalog_cache(path: Path) -> tuple[list[dict[str, Any]], float] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = _catalog_records(payload.get("instruments"))
        fetched_at = float(payload["fetched_at"])
        if records:
            return records, fetched_at
    except (OSError, TypeError, ValueError, KeyError):
        return None
    return None


def _write_catalog_cache(path: Path, records: list[dict[str, Any]], fetched_at: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": fetched_at,
        "environment": path.stem.rsplit("-", 1)[-1],
        "count": len(records),
        "instruments": records,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


async def load_instrument_catalog(session: Any, home: Path, environment: str) -> tuple[list[dict[str, Any]], str]:
    """Load a cached catalogue, refreshing it at most once per day."""
    path = _catalog_path(home, environment)
    cached = _read_catalog_cache(path)
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    if cached:
        records, fetched_at = cached
        age = max(0.0, now - fetched_at)
        if age <= CATALOG_TTL_SECONDS:
            return records, "cache"
    try:
        fetched = await _mcp_call(session, "search_instrument", {})
        records = _catalog_records(fetched)
        if not records:
            raise ProposalError("Trading 212 instrument catalogue was empty")
        _write_catalog_cache(path, records, now)
        return records, "refreshed"
    except Exception:
        if cached:
            records, fetched_at = cached
            age = max(0.0, now - fetched_at)
            if age <= CATALOG_MAX_STALE_SECONDS:
                return records, "stale-cache"
        raise


def _catalog_matches(catalog: list[dict[str, Any]], *, ticker: str = "", isin: str = "", short_name: str = "") -> list[dict[str, Any]]:
    ticker_upper = ticker.upper()
    isin_upper = isin.upper()
    short_upper = short_name.upper()
    exact = []
    for record in catalog:
        if isin_upper and _text(record.get("isin")).upper() == isin_upper:
            exact.append(record)
        elif ticker_upper and _text(record.get("ticker")).upper() == ticker_upper:
            exact.append(record)
        elif short_upper and _text(record.get("shortName")).upper() == short_upper:
            exact.append(record)
    return exact


def _cash_value(cash: Any, *keys: str) -> float:
    if isinstance(cash, dict):
        for key in keys:
            if key in cash:
                return _number(cash[key], key)
    return 0.0


def _report_inputs(state: dict[str, Any], results: list[dict[str, Any]], plan: OrderPlan, research: Any, candles: Any) -> dict[str, Any]:
    cash = state["fetch_account_cash"]
    positions = _records(state["fetch_all_open_positions"])
    total = _cash_value(cash, "total", "free", "freeCash")
    free = _cash_value(cash, "free", "freeCash", "available")
    invested = _cash_value(cash, "invested", "investedValue")
    pnl = _cash_value(cash, "ppl", "profitLoss", "result")
    # Pending orders: from fetch_all_orders (pending GTC orders only)
    # Filter out FILL orders - show only orders that are not yet filled
    pending_orders = [o for o in _records(state.get("fetch_all_orders", []))
                      if _text(o.get("status", "")).upper() not in ("FILLED", "WITHDRAWAL", "CANCELLED", "EXPIRED")]
    # New orders this run
    order_lines = []
    for result in results:
        if result.get("status") == "DRY_RUN":
            order_lines.append({
                "ticker": result.get("ticker", ""),
                "status": "DRY_RUN",
                "quantity": result.get("quantity", ""),
            })
        else:
            request = result["request"]
            readback = result["readback"]
            limit_price = request.get("limit_price", 0)
            if isinstance(limit_price, str):
                limit_price = float(limit_price) if limit_price else 0
            order_lines.append({
                "status": readback.get("status", "UNKNOWN"),
                "ticker": request.get("ticker", ""),
                "quantity": request.get("quantity", ""),
                "limit_price": limit_price,
                "order_id": result["response"].get("id", ""),
            })
    # Resolve candles for all pending orders (existing orders from account)
    # AND new order candidates from research
    candle_data = {}  # symbol -> {"candles": [...], "source": ...}
    if isinstance(candles, dict):
        candle_data.update(candles)
    # Also resolve candles for pending orders from the account
    if isinstance(candles, dict) and "pending_orders" in candles:
        pending_candles = candles["pending_orders"]
        for symbol, data in pending_candles.items():
            if symbol not in candle_data:
                candle_data[symbol] = data
    return {
        "balance": total, "free_cash": free, "invested": invested, "pnl": pnl,
        "positions": len(positions), "orders": order_lines, "pending_orders": pending_orders,
        "next_actions": plan.rejections[:5] or ["Re-check pending staged orders on the next run."],
        "candles": candles,
        "extraction": research.get("extraction", "provided by research command") if isinstance(research, dict) else "provided by research command",
        "sources": research.get("sources", []) if isinstance(research, dict) else [],
    }


def render_report(state: dict[str, Any], results: list[dict[str, Any]], plan: OrderPlan, research: Any, candles: Any, environment: str, llm_timed_out: bool = False) -> str:
    try:
        from scripts.t212_telegram_template import render
    except ModuleNotFoundError:
        from t212_telegram_template import render
    values = _report_inputs(state, results, plan, research, candles)
    values["llm_timed_out"] = llm_timed_out
    return render(environment, dt.datetime.now(dt.timezone.utc).isoformat(), **values)



async def _instrument_is_tradable(session: Any, candidate: Candidate) -> bool:
    """Check whether an instrument can be traded (has a primary exchange)."""
    try:
        matches = _records(await _mcp_call(session, "search_instrument", {"search_term": candidate.ticker}))
    except ProposalError:
        return False
    for item in matches:
        exchange = _text(item.get("exchangeCode", item.get("exchange", "")))
        primary_exchange = _text(item.get("primaryExchange", ""))
        if primary_exchange and _text(item.get("currencyCode", item.get("currency"))).upper() == candidate.currency:
            return True
    return False


async def run_pipeline(args: argparse.Namespace) -> str:
    from mcp.client.stdio import StdioServerParameters, stdio_client

    home = Path(os.environ.get("HERMES_HOME", "/opt/data"))
    binary = home / ".t212venv" / "bin" / "trading212-mcp-server"
    env = dict(os.environ)
    env.setdefault("ENVIRONMENT", configured_environment())
    server = StdioServerParameters(command=str(binary), args=["--transport", "stdio"], env=env, cwd=str(home))

    # Use async with to properly manage the stdio_client's internal task group
    # The streams stay alive for the entire pipeline execution
    async with stdio_client(server) as (read, write):
        session = ClientSession(read, write, client_info=Implementation(
            name="trading212-portfolio-automation",
            version="1.0.0",
        ))
        try:
            await session.__aenter__()
            # Initialize the session before calling any tools
            await session.initialize()
            # Load the authoritative Trading 212 catalogue once per run.
            # Fresh entries are cached for 24h; a cache up to 72h old is allowed
            # only as a rate-limit fallback.
            catalog, catalog_source = await load_instrument_catalog(session, home, args.environment)
            print(f"  [t212] instrument catalogue: {len(catalog)} records ({catalog_source})", file=sys.stderr)
            state = await collect_state(session)
            # Source 2: research (news + candidate tickers)
            research = run_research(args.research_command)
            # Merge candidate tickers: source 1 (existing orders) + source 2 (research candidates)
            # Source 1 (guaranteed tradeable) + Source 2 (research candidates)
            # Get all tickers from both sources
            existing_tickers = set()
            for pos in state.get("fetch_all_open_positions", []):
                t = _text(pos.get("ticker"))
                if t:
                    existing_tickers.add(t)
            for order in _records(state.get("fetch_all_orders", [])):
                if isinstance(order, dict):
                    instrument = order.get("instrument")
                    if isinstance(instrument, dict):
                        t = _text(instrument.get("ticker"))
                    else:
                        t = _text(instrument or "")
                else:
                    t = ""
                if t:
                    existing_tickers.add(t)
            # Merge candidates from LLM with existing positions
            # All candidates from both sources
            prompt = build_llm_prompt(state, research, existing_tickers)
            llm_timed_out = False
            try:
                candidates = call_llm(prompt, args.llm_command)
            except Exception:
                # call_llm already prints a warning to stderr and returns empty list
                # on timeout; record that we fell back to empty candidates
                llm_timed_out = True
                candidates = []
            # Validate every research candidate against the cached catalogue before
            # it can enter sizing or order execution.
            # Validate every research candidate against the cached catalogue before
            # it can enter sizing or order execution.
            validated_candidates: list[Candidate] = []
            for candidate in candidates:
                matches = _catalog_matches(catalog, ticker=candidate.ticker, isin=candidate.isin, short_name=candidate.ticker)
                if len(matches) != 1:
                    print(f"  [t212] rejecting {candidate.ticker}: catalogue match count={len(matches)}", file=sys.stderr)
                    continue
                match = matches[0]
                validated_candidates.append(Candidate(
                    ticker=_text(match.get("ticker")),
                    isin=_text(match.get("isin")),
                    currency=_text(match.get("currencyCode", match.get("currency"))).upper(),
                    exchange=candidate.exchange,
                    price=candidate.price,
                    allocation_pct=candidate.allocation_pct,
                    rationale=candidate.rationale,
                    stop_loss_pct=candidate.stop_loss_pct,
                ))
            candidates = validated_candidates
            # Build order plan: only new candidates (not already in positions/pending)
            cash = _cash_value(state["fetch_account_cash"], "free", "freeCash", "available")
            positions = _records(state["fetch_all_open_positions"])
            pending_orders = _records(state["fetch_all_orders"])
            existing_tickers_set = set(_text(p.get("ticker")) for p in positions + pending_orders)
            new_candidates = [c for c in candidates if _text(c.ticker) not in existing_tickers_set]
            plan = build_order_plan(
                free_cash=cash,
                positions=positions,
                pending_orders=pending_orders,
                candidates=new_candidates,
                policy=Policy(),
            )
            # Resolve candles for both required sources on every run:
            # existing positions/pending orders plus new research candidates.
            account_instruments = _account_candle_instruments(state, catalog)
            candles = await _resolve_candles(session, new_candidates, plan, account_instruments, catalog)
            results = await execute_orders(session, plan, execute=args.execute)
            report = render_report(state, results, plan, research, candles, args.environment.upper(), llm_timed_out)
        except BaseException as exc:
            print(f"t212 runner stopped: {exc}", file=sys.stderr)
            raise
        finally:
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
    # async with block exits here: streams are closed, task group is cleaned up
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-command", required=True)
    parser.add_argument("--llm-command", required=True, help="command that reads the prompt on stdin and prints JSON")
    parser.add_argument("--deliver-command", help="optional command that reads the rendered report on stdin")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--environment", default=configured_environment())
    args = parser.parse_args(argv)
    if args.execute and args.environment.lower() == "live" and not args.allow_live:
        parser.error("--allow-live is required for live execution")
    loop = asyncio.new_event_loop()
    try:
        # Use async with to properly manage the stdio_client's internal task group
        # The streams stay alive for the entire pipeline execution, and the
        # task group is properly cleaned up when the async with block exits.
        report = loop.run_until_complete(run_pipeline(args))
    finally:
        loop.close()

    # Print the report to stdout so the Hermes cron runner captures and
    # persists it to the output directory.
    if args.deliver_command:
        # Hand the rendered report to the deliver command.
        result = subprocess.run(
            args.deliver_command,
            input=report,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"Delivering report to {args.deliver_command} failed: {result.stderr}", file=sys.stderr)
    else:
        print(report)
    return 0


def _account_candle_instruments(state: dict[str, Any], catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize account positions and pending orders for candle collection."""
    instruments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source_name in ("fetch_all_open_positions", "fetch_all_orders"):
        for record in _records(state.get(source_name, [])):
            nested_value = record.get("instrument")
            nested: dict[str, Any] = dict(nested_value) if isinstance(nested_value, dict) else {}
            merged: dict[str, Any] = {**nested, **record}
            ticker = _text(nested.get("ticker") or record.get("ticker"))
            isin = _text(nested.get("isin") or record.get("isin"))
            currency = _text(
                nested.get("currencyCode") or nested.get("currency") or
                record.get("currencyCode") or record.get("currency")
            ).upper()
            exchange = _text(
                nested.get("exchange") or nested.get("exchangeCode") or
                record.get("exchange") or record.get("exchangeCode")
            ).upper()
            if not ticker:
                continue
            key = (ticker, isin)
            if key in seen:
                continue
            seen.add(key)
            instruments.append({
                "ticker": ticker,
                "isin": isin,
                "currency": currency,
                "exchange": exchange,
                "twelve_symbol": merged.get("twelve_symbol") or merged.get("twelveSymbol"),
                "yahoo_symbol": merged.get("yahoo_symbol") or merged.get("yahooSymbol"),
                "provider_symbol_hint": merged.get("provider_symbol_hint") or merged.get("providerSymbol"),
            })
    for instrument in instruments:
        matches = _catalog_matches(catalog, ticker=instrument["ticker"], isin=instrument["isin"])
        if not matches:
            continue
        match = matches[0]
        instrument["isin"] = instrument["isin"] or _text(match.get("isin"))
        instrument["currency"] = instrument["currency"] or _text(match.get("currencyCode", match.get("currency"))).upper()
        instrument["provider_symbol_hint"] = instrument["provider_symbol_hint"] or match.get("shortName")
    return instruments


async def _resolve_candles(
    session: Any,
    candidates: list[Candidate],
    plan: OrderPlan,
    account_instruments: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    """Download candles for account exposure and research-selected candidates."""
    import subprocess
    import json as json_mod

    instruments = list(account_instruments)
    existing_keys = {(item.get("ticker"), item.get("isin")) for item in instruments}
    # Existing account instruments are resolved from the cached catalogue.
    for instrument in instruments:
        if all(instrument.get(field) for field in ("isin", "currency")):
            continue
        matches = _catalog_matches(catalog, ticker=instrument["ticker"], isin=instrument.get("isin", ""))
        if matches:
            match = matches[0]
            instrument["isin"] = instrument.get("isin") or _text(match.get("isin"))
            instrument["currency"] = instrument.get("currency") or _text(match.get("currencyCode", match.get("currency"))).upper()
            instrument["provider_symbol_hint"] = instrument.get("provider_symbol_hint") or match.get("shortName")

    for candidate in candidates:
        matches = _catalog_matches(catalog, ticker=candidate.ticker, isin=candidate.isin)
        match = matches[0] if matches else {}
        instrument = {
            "ticker": _text(match.get("ticker") or candidate.ticker),
            "isin": _text(match.get("isin") or candidate.isin),
            "currency": _text(match.get("currencyCode", match.get("currency"))) or candidate.currency,
            "exchange": _text(match.get("exchange", match.get("exchangeCode"))) or candidate.exchange,
            "twelve_symbol": match.get("twelve_symbol") or match.get("twelveSymbol"),
            "yahoo_symbol": match.get("yahoo_symbol") or match.get("yahooSymbol"),
            "provider_symbol_hint": match.get("provider_symbol_hint") or match.get("providerSymbol"),
        }
        key = (instrument["ticker"], instrument["isin"])
        if key not in existing_keys:
            instruments.append(instrument)
            existing_keys.add(key)

    if not instruments:
        return {}
    script = Path(__file__).parent / "candle_analysis.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--instruments", json_mod.dumps(instruments), "--days", "400"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            return {item["ticker"]: {"candles": None, "resolved": False, "source": "failed", "error": result.stderr.strip() or "candle collector failed"} for item in instruments}
        payload = json_mod.loads(result.stdout)
    except Exception as exc:
        return {item["ticker"]: {"candles": None, "resolved": False, "source": "failed", "error": str(exc)} for item in instruments}

    output: dict[str, Any] = {}
    for item in payload.get("results", []):
        ticker = _text(item.get("ticker")) or "unknown"
        if item.get("status") == "ok":
            output[ticker] = {
                "candles": item.get("indicators") or {},
                "resolved": True,
                "source": item.get("source") or item.get("provider"),
                "bars": (item.get("indicators") or {}).get("bars"),
                "latest": (item.get("indicators") or {}).get("as_of"),
            }
        else:
            output[ticker] = {
                "candles": None,
                "resolved": False,
                "source": "unavailable",
                "error": item.get("error") or "no parseable candle data",
            }
    return output


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
