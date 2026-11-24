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
    max_allocation_pct: float = 0.20


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


@dataclass(frozen=True)
class PlannedExitOrder:
    ticker: str
    quantity: float
    limit_price: float
    fill_price: float
    take_profit_pct: float


@dataclass(frozen=True)
class StopLossAction:
    ticker: str
    quantity: float
    fill_price: float
    stop_price: float
    take_profit_order_id: int


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


def _configured_fraction(name: str, default: float) -> float:
    """Read a fractional exit setting from env or the profile config."""
    raw = os.environ.get(f"T212_{name}", "").strip()
    if not raw:
        config_path = Path(os.environ.get("HERMES_HOME", "/opt/data")) / "config.yaml"
        try:
            for line in config_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith(f"{name}:"):
                    raw = line.split(":", 1)[1].strip().strip("'\"")
                    break
        except OSError:
            pass
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    if not 0 < value < 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def configured_take_profit_pct() -> float:
    """Default short-term profit target: 3% above average fill."""
    return _configured_fraction("TAKE_PROFIT_PCT", 0.03)


def configured_stop_loss_pct() -> float:
    """Default short-term protective stop: 1.5% below average fill."""
    return _configured_fraction("STOP_LOSS_PCT", 0.015)


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


def build_take_profit_plan(
    *,
    positions: Iterable[dict[str, Any]],
    pending_orders: Iterable[dict[str, Any]],
    take_profit_pct: float,
) -> list[PlannedExitOrder]:
    """Create one full-position sell limit for each position without a sell pending."""
    if not 0 < take_profit_pct < 1:
        raise ValueError("take_profit_pct must be between 0 and 1")
    pending_sells: set[str] = set()
    pending_buys: set[str] = set()
    for order in pending_orders:
        raw_nested = order.get("instrument")
        nested: dict[str, Any] = raw_nested if isinstance(raw_nested, dict) else {}
        ticker = _text(order.get("ticker") or nested.get("ticker"))
        side = _text(order.get("side")).upper()
        try:
            quantity = float(order.get("quantity", 0) or 0)
        except (TypeError, ValueError):
            quantity = 0
        if ticker and (side == "SELL" or quantity < 0):
            pending_sells.add(ticker)
        if ticker and side == "BUY" and quantity > 0:
            pending_buys.add(ticker)

    exits: list[PlannedExitOrder] = []
    for position in positions:
        raw_nested = position.get("instrument")
        nested: dict[str, Any] = raw_nested if isinstance(raw_nested, dict) else {}
        ticker = _text(position.get("ticker") or nested.get("ticker"))
        if not ticker or ticker in pending_sells or ticker in pending_buys:
            continue
        try:
            quantity = float(position.get("quantity", 0) or 0)
            fill_price = float(position.get("averagePrice", position.get("average_price", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if quantity <= 0 or fill_price <= 0:
            continue
        target = round(fill_price * (1 + take_profit_pct), 4)
        exits.append(PlannedExitOrder(ticker, -quantity, target, fill_price, take_profit_pct))
    return exits


def build_protective_exit_plan(
    *,
    positions: Iterable[dict[str, Any]],
    pending_orders: Iterable[dict[str, Any]],
    take_profit_pct: float,
    stop_loss_pct: float,
) -> list[PlannedExitOrder]:
    """Build one take-profit sell for each filled, unprotected position.

    The stop loss is handled by the runner on later cycles. Trading 212 reserves
    the shares for a pending sell, so a TP and broker-side stop cannot coexist
    at full quantity.
    """
    if not 0 < take_profit_pct < 1 or not 0 < stop_loss_pct < 1:
        raise ValueError("exit percentages must be between 0 and 1")
    pending_sells: set[str] = set()
    pending_buys: set[str] = set()
    for order in pending_orders:
        raw_nested = order.get("instrument")
        nested: dict[str, Any] = raw_nested if isinstance(raw_nested, dict) else {}
        ticker = _text(order.get("ticker") or nested.get("ticker"))
        side = _text(order.get("side")).upper()
        try:
            quantity = float(order.get("quantity", 0) or 0)
        except (TypeError, ValueError):
            quantity = 0
        if ticker and (side == "SELL" or quantity < 0):
            pending_sells.add(ticker)
        if ticker and side == "BUY" and quantity > 0:
            pending_buys.add(ticker)

    exits: list[PlannedExitOrder] = []
    for position in positions:
        raw_nested = position.get("instrument")
        nested: dict[str, Any] = raw_nested if isinstance(raw_nested, dict) else {}
        ticker = _text(position.get("ticker") or nested.get("ticker"))
        if not ticker or ticker in pending_sells or ticker in pending_buys:
            continue
        try:
            quantity = float(position.get("quantity", 0) or 0)
            fill_price = float(position.get("averagePrice", position.get("average_price", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if quantity <= 0 or fill_price <= 0:
            continue
        target = round(fill_price * (1 + take_profit_pct), 4)
        exits.append(PlannedExitOrder(ticker, -quantity, target, fill_price, take_profit_pct))
    return exits


def build_stop_loss_actions(
    *,
    positions: Iterable[dict[str, Any]],
    pending_orders: Iterable[dict[str, Any]],
    current_prices: dict[str, float],
    stop_loss_pct: float,
) -> list[StopLossAction]:
    """Plan TP cancellation plus market sell when a stop threshold is reached."""
    if not 0 < stop_loss_pct < 1:
        raise ValueError("stop_loss_pct must be between 0 and 1")
    position_map: dict[str, tuple[float, float]] = {}
    for position in positions:
        ticker = _text(position.get("ticker"))
        try:
            quantity = float(position.get("quantity", 0) or 0)
            fill_price = float(position.get("averagePrice", position.get("average_price", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if ticker and quantity > 0 and fill_price > 0:
            position_map[ticker] = (quantity, fill_price)

    actions: list[StopLossAction] = []
    for order in pending_orders:
        raw_nested = order.get("instrument")
        nested: dict[str, Any] = raw_nested if isinstance(raw_nested, dict) else {}
        ticker = _text(order.get("ticker") or nested.get("ticker"))
        side = _text(order.get("side")).upper()
        order_type = _text(order.get("type") or order.get("orderType")).upper()
        try:
            order_quantity = float(order.get("quantity", 0) or 0)
        except (TypeError, ValueError):
            order_quantity = 0
        if not ticker or ticker not in position_map or not (side == "SELL" or order_quantity < 0):
            continue
        if order_type and order_type not in {"LIMIT", "LIMIT_ORDER"} and order.get("limitPrice", order.get("limit_price")) is None:
            continue
        raw_id = order.get("id", order.get("orderId"))
        if raw_id is None:
            continue
        try:
            order_id = int(raw_id)
            quantity, fill_price = position_map[ticker]
            current_price = float(current_prices.get(ticker, 0) or 0)
        except (TypeError, ValueError):
            continue
        stop_price = round(fill_price * (1 - stop_loss_pct), 4)
        if current_price > 0 and current_price <= stop_price:
            actions.append(StopLossAction(ticker, -quantity, fill_price, stop_price, order_id))
    return actions


def _current_position_prices(positions: Iterable[dict[str, Any]], candles: Any) -> dict[str, float]:
    prices: dict[str, float] = {}
    for position in positions:
        ticker = _text(position.get("ticker"))
        raw = position.get("currentPrice", position.get("current_price"))
        try:
            if ticker and raw is not None:
                prices[ticker] = float(raw)
        except (TypeError, ValueError):
            pass
    if isinstance(candles, dict):
        for ticker, item in candles.items():
            if ticker in prices or not isinstance(item, dict):
                continue
            indicators = item.get("candles") or {}
            try:
                if indicators.get("last_close") is not None:
                    prices[ticker] = float(indicators["last_close"])
            except (TypeError, ValueError):
                pass
    return prices


def orphan_sell_order_ids(
    *,
    positions: Iterable[dict[str, Any]],
    pending_orders: Iterable[dict[str, Any]],
) -> list[int]:
    """Find active sell orders whose position is no longer open."""
    position_tickers = set()
    for position in positions:
        raw_nested = position.get("instrument")
        nested: dict[str, Any] = raw_nested if isinstance(raw_nested, dict) else {}
        ticker = _text(position.get("ticker") or nested.get("ticker"))
        if ticker:
            position_tickers.add(ticker)
    ids: list[int] = []
    for order in pending_orders:
        raw_nested = order.get("instrument")
        nested: dict[str, Any] = raw_nested if isinstance(raw_nested, dict) else {}
        ticker = _text(order.get("ticker") or nested.get("ticker"))
        side = _text(order.get("side")).upper()
        try:
            quantity = float(order.get("quantity", 0) or 0)
            raw_id = order.get("id", order.get("orderId"))
            if raw_id is None:
                continue
            order_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if ticker and ticker not in position_tickers and (side == "SELL" or quantity < 0):
            ids.append(order_id)
    return ids


def _identity_matches(candidate: Candidate, record: dict[str, Any]) -> bool:
    ticker = _text(record.get("ticker"))
    isin = _text(record.get("isin"))
    return bool(ticker == candidate.ticker or (isin and isin == candidate.isin))


def build_order_plan(
    *,
    free_cash: float,
    positions: Iterable[dict[str, Any]],
    pending_orders: Iterable[dict[str, Any]],
    candidates: Iterable[Candidate],
    policy: Policy,
    catalog: Iterable[dict[str, Any]] | None = None,
) -> OrderPlan:
    """Build buy orders without performing any external writes.

    The account instrument catalogue (instruments-live.json for the active
    environment) is the authoritative tradable-instrument list for this
    account. Every order candidate is cross-referenced against it here:
    only instruments that resolve to exactly one tradable catalogue record
    (exact ticker *or* exact ISIN) may be sized for the broker. Partial,
    ambiguous or unknown matches are deterministic rejections at plan stage,
    never soft failures that later surface as broker rejections.
    """
    cash = _number(free_cash, "free_cash")
    if cash < 0:
        raise ValueError("free_cash cannot be negative")
    position_records = list(positions)
    pending_records = list(pending_orders)
    remaining = cash * (1 - policy.reserve_pct)
    orders: list[PlannedOrder] = []
    rejections: list[str] = []
    catalog_records = list(catalog or [])

    for candidate in candidates:
        if _text(candidate.currency).upper() != "EUR":
            rejections.append(f"{candidate.ticker}: non-EUR candidate")
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

        # Precise cross-reference against the account instrument catalogue:
        # only instruments resolved to exactly one tradable catalogue record
        # (exact ticker OR exact ISIN) may be sized for the broker. Partial and
        # ambiguous matches are deterministic rejections now, not broker
        # rejections later.
        matches = _catalog_matches(catalog_records, ticker=candidate.ticker, isin=candidate.isin)
        if not matches:
            rejections.append(f"{candidate.ticker}: no instrument catalogue record (not tradable in this account)")
            continue
        if len(matches) > 1:
            rejections.append(f"{candidate.ticker}: {len(matches)} instrument catalogue records match (ambiguous, rejected)")
            continue
        record = matches[0]
        instrument_type = _text(record.get("type", "")).upper()
        if instrument_type not in ("ETF", "STOCK"):
            rejections.append(f"{candidate.ticker}: catalogue record type '{instrument_type}' is not an orderable equity/ETF")
            continue
        if _text(record.get("currencyCode", record.get("currency"))).upper() != "EUR":
            rejections.append(f"{candidate.ticker}: catalogue record is {record.get('currencyCode', record.get('currency'))}, not EUR")
            continue

        # Keep the LLM's requested allocation when it is within policy, but
        # cap oversized proposals before converting them into an order value.
        allocation_pct = min(candidate.allocation_pct, policy.max_allocation_pct)
        requested = cash * (1 - policy.reserve_pct) * allocation_pct
        tranche_cap = cash * (1 - policy.reserve_pct) * policy.first_tranche_pct
        notional = min(requested, tranche_cap, remaining)
        if notional < policy.min_order_value:
            # Promote small proposals to the broker minimum when the reserved
            # cash still covers it. Round quantity upward so the resulting
            # notional cannot fall below the minimum after 0.01-unit precision.
            if remaining < policy.min_order_value:
                rejections.append(f"{candidate.ticker}: below minimum order value or reserve")
                continue
            notional = policy.min_order_value
            quantity = math.ceil(notional / candidate.price * 100) / 100
        else:
            quantity = round(notional / candidate.price * 100) / 100
        notional = round(quantity * candidate.price, 8)
        if quantity <= 0 or notional < policy.min_order_value:
            rejections.append(f"{candidate.ticker}: below minimum order value or reserve")
            continue
        orders.append(PlannedOrder(candidate.ticker, candidate.isin, quantity, candidate.price, notional, candidate.rationale))
        remaining = round(remaining - notional, 8)
        pending_records.append({"ticker": candidate.ticker, "isin": candidate.isin, "quantity": quantity})
    return OrderPlan(orders, rejections, remaining)


def _carry_over_order_rejections(plan: OrderPlan, results: Iterable[dict[str, Any]]) -> OrderPlan:
    """Deterministically promote order-level broker rejections into a new OrderPlan.

    A 4xx/broker hard-validation failure on one order ("price too far",
    "instrument can not be traded", malformed response, ...) is permanent for
    that specific payload: retrying the same invalid order never helps and
    clutters the run with repeated identical failures. Record it once as a
    deterministic, human-readable rejection row in the plan's rejection
    block, so the rendered report's Next actions list explains exactly which
    orders the broker rejected and why, instead of showing only a muted
    REJECTED_BY_BROKER row under "Orders this run".
    """
    seen: set[tuple[str, str]] = set()
    promoted: list[str] = []
    for result in results:
        status = result.get("status")
        if status not in ("REJECTED_BY_BROKER", "ERROR"):
            continue
        request = result.get("request") or {}
        ticker = _text(result.get("ticker") or request.get("ticker") or "")
        reason = _text(result.get("reason") or "")
        if not reason and isinstance(request, dict):
            arguments = request.get("arguments")
            if isinstance(arguments, dict):
                reason = _text(
                    arguments.get("limit_price")
                    or arguments.get("target_price")
                    or request.get("limit_price")
                    or ""
                )
        key = (ticker, reason)
        if key in seen:
            continue
        seen.add(key)
        if ticker:
            promoted.append(f"{ticker}: broker rejected order ({reason})")
        else:
            promoted.append(f"order: broker rejected ({reason})")
    if promoted:
        merged = list(dict.fromkeys(plan.rejections + promoted))
        # Deterministic next-actions list is capped at 5 rows in the template;
        # keep the newest order-level rejections at the tail.
        return OrderPlan(
            orders=plan.orders,
            rejections=merged[-20:],
            remaining_cash=plan.remaining_cash,
        )
    return plan


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
    if completed.stderr:
        # Persist research diagnostics in the run log; otherwise extraction
        # failures are undiagnosable after the fact.
        print(f"  [t212] research stderr: {completed.stderr.strip()[-1500:]}", file=sys.stderr)
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
        "Select listed stocks and ETFs suitable for short-term, unleveraged trades; do not choose CFDs, leverage, inverse products, shorts, or options. "
        "For ETFs prefer distributing share classes (the account objective is withdrawing cash); use exact full Trading 212 tickers and ISINs, never bare symbols. "
        "Use current catalysts, liquidity, volatility, and technical context from the supplied research. "
        "Every filled long position will receive a take-profit limit and a protective stop-loss market order. "
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
    raise ProposalError("LLM selector exhausted retries")


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
            if not text:
                if name == "cancel_order":
                    # Trading 212 returns an empty 200/204 response for a
                    # successful DELETE. Empty content is therefore a valid
                    # write result, not malformed JSON.
                    return None
                if name in {"fetch_all_open_positions", "fetch_all_orders", "search_instrument", "fetch_recent_activity"}:
                    return []
            try:
                return _decode_json_stream(text)
            except (json.JSONDecodeError, ValueError) as exc:
                if name == "cancel_order":
                    # The Trading 212 MCP tool can serialize a successful
                    # DELETE as non-JSON text (and can do the same after the
                    # order is already gone). Cancellation is cleanup and the
                    # desired end state is "order not active", so do not retry
                    # the DELETE or turn it into a cron failure.
                    print(
                        f"  [t212] API call 'cancel_order' returned a non-JSON "
                        f"cleanup response; treating cancellation as complete",
                        file=sys.stderr,
                    )
                    return None
                # Trading 212 / MCP server returned non-JSON data (transient
                # transport or server parse blip). Retry with bounded backoff;
                # persistent payloads still fail loudly, preserving the cause.
                if attempt < max_attempts:
                    wait = min(base_delay * (2 ** (attempt - 1)), 30.0)
                    print(f"  [t212] API call '{name}' returned non-JSON data ({exc}); retry {attempt}/{max_attempts} in {wait:.1f}s", file=sys.stderr)
                    await asyncio.sleep(wait)
                    continue
                raise UnknownWriteState(f"{name} returned non-JSON data") from exc
        except Exception as exc:
            error_text = str(exc)
            if name == "cancel_order" and (
                "404" in error_text or "not found" in error_text.lower()
            ):
                # Cleanup is idempotent: an already-cancelled/deleted order is
                # in the desired final state.
                return None
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
        try:
            values[name] = await _mcp_call(session, name, args)
        except Exception as exc:
            if name != "fetch_recent_activity":
                raise
            # Activity is an auxiliary audit feed. Its composite endpoint can
            # fail independently of the account/positions/orders endpoints; do
            # not abort trading decisions when that feed is unavailable.
            print(f"  [t212] recent activity unavailable; continuing without it: {exc}", file=sys.stderr)
            values[name] = []
    return values


async def execute_orders(
    session: Any,
    plan: OrderPlan,
    *,
    execute: bool,
    candles: dict[str, Any] | None = None,
    catalog_records: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    results = []
    for order in plan.orders:
        if not execute:
            results.append({"ticker": order.ticker, "status": "DRY_RUN", "quantity": order.quantity})
            continue
        # Limit orders are rejected by Trading 212 as "price too far" when the
        # price is far from the latest market close. Where candle data is
        # available, use the latest close as the limit price when the estimate
        # is off by more than ~5% so orders are placed at a valid price.
        limit_price = order.limit_price
        if candles:
            item = candles.get(order.ticker) or {}
            indicators = (item.get("candles") or {})
            last_close = indicators.get("last_close")
            if last_close is None:
                # No floor data: do not send a possibly-stale limit price.
                # Defer this order and have the next run re-fetch candles.
                results.append({
                    "ticker": order.ticker,
                    "status": "PENDING_FLOOR_MISSING",
                    "limit_price": order.limit_price,
                    "reason": "no candle floor data available",
                })
                continue
            if order.limit_price > 0 and abs(order.limit_price - last_close) / last_close > 0.05:
                limit_price = last_close
        print(f"  [t212] placing order ticker={order.ticker} qty={order.quantity} limit_price={limit_price}", file=sys.stderr)
        # Pre-trade lot check: compute the instrument's minimum tradable lot
        # from the LIVE account instrument reference the pipeline already
        # loaded, and refuse to place an order below that lot. Deterministic
        # rejection, no broker call, no wasted capital.
        min_lot = None
        if catalog_records is not None:
            min_lot = instrument_min_trade_quantity(catalog_records, order.ticker)
        if min_lot is not None and order.quantity < min_lot:
            print(f"  [t212] rejecting order below minimum tradable lot ticker={order.ticker} qty={order.quantity} min_lot={min_lot}", file=sys.stderr)
            results.append({
                "ticker": order.ticker,
                "status": "REJECTED_BY_BROKER",
                "reason": f"below minimum tradable lot ({min_lot} shares)",
                "quantity": order.quantity,
                "limit_price": limit_price,
            })
            continue

        try:
            response = await _mcp_call(session, "place_limit_order", {
                "ticker": order.ticker, "quantity": order.quantity,
                "limit_price": limit_price, "time_validity": "GOOD_TILL_CANCEL",
            })
        except UnknownWriteState as exc:
            # Broker validation rejected the payload outright (e.g. "price too far")
            # a single order must never abort the whole batch; record it as a
            # deterministic rejection and keep processing the remaining orders.
            print(f"  [t212] order rejected by broker {order.ticker}: {exc}", file=sys.stderr)
            results.append({
                "ticker": order.ticker,
                "status": "REJECTED_BY_BROKER",
                "reason": str(exc),
                "quantity": order.quantity,
                "limit_price": limit_price,
            })
            continue
        except Exception as exc:  # transient write path (rate-limit / timeout / blip)
            print(f"  [t212] write failed {order.ticker}: {exc}", file=sys.stderr)
            results.append({"ticker": order.ticker, "status": "ERROR", "reason": str(exc)})
            continue
        # Read back the order to verify it was placed
        try:
            readback = await _mcp_call(session, "fetch_order", {"order_id": int(response["id"])})
        except Exception as exc:
            # Transient readback blip: record it deterministically and keep the
            # run going; a single unverifiable fill must not abort the batch.
            print(f"  [t212] readback failed {order.ticker}: {exc}", file=sys.stderr)
            readback = None
        results.append({"status": "PLACED", "request": asdict(order), "response": response, "readback": readback})
    return results


async def execute_protective_exits(
    session: Any,
    exits: list[PlannedExitOrder],
    *,
    execute: bool,
) -> list[dict[str, Any]]:
    """Place one take-profit limit for each newly protected position."""
    results: list[dict[str, Any]] = []
    for item in exits:
        request = {
            **asdict(item),
            "order_type": "TAKE_PROFIT",
            "arguments": {
                "ticker": item.ticker,
                "quantity": item.quantity,
                "limit_price": item.limit_price,
                "time_validity": "GOOD_TILL_CANCEL",
            },
        }
        if not execute:
            results.append({"request": request, "status": "DRY_RUN"})
            continue
        print(
            f"  [t212] placing take_profit ticker={item.ticker} "
            f"qty={item.quantity} target={item.limit_price}", file=sys.stderr,
        )
        try:
            response = await _mcp_call(session, "place_limit_order", request["arguments"])
            if not isinstance(response, dict) or not response.get("id"):
                raise UnknownWriteState("place_limit_order returned no verifiable order id")
            readback = await _mcp_call(session, "fetch_order", {"order_id": int(response["id"])})
            results.append({"status": "PLACED", "request": request, "response": response, "readback": readback})
        except UnknownWriteState as exc:
            results.append({"status": "REJECTED_BY_BROKER", "ticker": item.ticker, "reason": str(exc), "request": request})
        except Exception as exc:
            results.append({"status": "ERROR", "ticker": item.ticker, "reason": str(exc), "request": request})
    return results


async def execute_stop_loss_actions(
    session: Any,
    actions: list[StopLossAction],
    *,
    execute: bool,
) -> list[dict[str, Any]]:
    """Cancel a breached TP, then execute a verified market sell."""
    results: list[dict[str, Any]] = []
    for action in actions:
        request = {**asdict(action), "order_type": "STOP_LOSS_MARKET"}
        if not execute:
            results.append({"request": request, "status": "DRY_RUN"})
            continue
        print(
            f"  [t212] stop threshold reached ticker={action.ticker} "
            f"current<=stop {action.stop_price}; cancelling TP {action.take_profit_order_id}",
            file=sys.stderr,
        )
        try:
            await _mcp_call(session, "cancel_order", {"order_id": action.take_profit_order_id})
            try:
                await _mcp_call(session, "fetch_order", {"order_id": action.take_profit_order_id})
            except Exception as exc:
                # Trading 212 may remove a cancelled order immediately, while
                # the MCP layer exposes that 404 as a generic non-JSON error.
                print(
                    f"  [t212] TP cancellation readback unavailable for order "
                    f"{action.take_profit_order_id}: {exc}",
                    file=sys.stderr,
                )
            response = await _mcp_call(session, "place_market_order", {"ticker": action.ticker, "quantity": action.quantity})
            if not isinstance(response, dict) or not response.get("id"):
                raise UnknownWriteState("place_market_order returned no verifiable order id")
            readback = await _mcp_call(session, "fetch_order", {"order_id": int(response["id"])})
            results.append({"request": request, "response": response, "readback": readback, "status": "STOP_LOSS_FILLED"})
        except UnknownWriteState as exc:
            results.append({"status": "ERROR", "ticker": action.ticker, "reason": str(exc), "request": request})
        except Exception as exc:
            results.append({"status": "ERROR", "ticker": action.ticker, "reason": str(exc), "request": request})
    return results


def _filled_activity_signatures(value: Any) -> set[str]:
    """Return canonical activity records that indicate a filled order."""
    found: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            values = [str(item.get(key, "")).upper() for key in ("status", "type", "eventType", "action", "event")]
            if any("FILL" in value for value in values):
                found.add(json.dumps(item, sort_keys=True, default=str, separators=(",", ":")))
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return found


def _new_filled_activity(before: Any, after: Any) -> bool:
    """Detect a newly visible filled-order activity record."""
    return bool(_filled_activity_signatures(after) - _filled_activity_signatures(before))


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


CATALOG_TTL_SECONDS = 7 * 24 * 60 * 60  # weekly: re-download when older than 1 week
CATALOG_MAX_STALE_SECONDS = 7 * 24 * 60 * 60  # stale fallback window matches the weekly refresh


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
    """Load a cached catalogue with the per-instrument minimum tradable lot
    (minTradeQuantity), refreshing it at most once a week (re-download when
    older than 1 week). The min lot is part of the same LIVE account
    instrument catalogue payload, so no separate data source is needed."""

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


def instrument_min_trade_quantity(catalog_records: Iterable[dict[str, Any]], ticker: str) -> float | None:
    """Minimum tradable lot (in shares) of *ticker* from the account's
    instrument reference (the catalogue the pipeline loads, or the live
    trading212-mcp-server instrument list).

    Fields used: ``minTradeQuantity`` / ``min_trade_quantity`` (the fields used
    by the cached catalogue and by the live instrument model, respectively).
    Any populated value is returned as float; a missing/zero/unparseable value
    does not block an order but is reported as ``None``, so callers must not
    treat "lot unknown" as "no minimum".
    """
    for record in catalog_records:
        record_ticker = _text(record.get("ticker"))
        if record_ticker.upper() == ticker.upper():
            for key in ("minTradeQuantity", "min_trade_quantity"):
                value = record.get(key)
                if value not in (None, "", 0):
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        return None
    return None


def instrument_is_tradable(catalog_records: Iterable[dict[str, Any]], ticker: str) -> bool:
    """True if the ticker resolves to exactly one tradable record in the
    account instrument catalogue (type equity/ETF, EUR settlement)."""
    matches = [r for r in catalog_records if _text(r.get("ticker")).upper() == ticker.upper()]
    for record in matches:
        if _text(record.get("type", "")).upper() in ("ETF", "STOCK") and \
                _text(record.get("currencyCode", record.get("currency"))).upper() == "EUR":
            return True
    return False


def _is_distributing_record(record: dict[str, Any]) -> bool:
    """Distribution policy comes from the fund name, NOT the ticker suffix.

    Trading 212 ticker suffixes encode the listing venue (d=Xetra, a=Amsterdam,
    l=London, s=Swiss, m=Milan, ...), not Acc/Dist. The authoritative marker is
    '(Dist)' / '(Acc)' in the instrument name.
    """
    return "(DIST)" in _text(record.get("name")).upper()


def _resolve_listing(
    catalog: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    candidate: Candidate,
    account_currency: str,
) -> tuple[dict[str, Any] | None, str]:
    """Pick one verified listing from ambiguous catalogue matches.

    Order of preference: account-currency settlement, distributing share class
    (the account objective is cash withdrawal), then exact ISIN / ticker identity.
    A uniquely resolved accumulating ETF is swapped to its distributing sibling
    share class when exactly one exists in the same currency.
    """
    if not matches:
        return None, "no catalogue match"
    pool = [m for m in matches if _text(m.get("currencyCode", m.get("currency"))).upper() == account_currency]
    if not pool:
        return None, f"no {account_currency}-settled listing among {len(matches)} matches"
    dist_pool = [m for m in pool if _is_distributing_record(m)]
    if dist_pool:
        pool = dist_pool
    selected: dict[str, Any] | None = None
    if len(pool) == 1:
        selected = pool[0]
    else:
        by_isin = [m for m in pool if candidate.isin and _text(m.get("isin")).upper() == candidate.isin.upper()]
        by_ticker = [m for m in pool if _text(m.get("ticker")).upper() == candidate.ticker.upper()]
        if len(by_isin) == 1:
            selected = by_isin[0]
        elif len(by_ticker) == 1:
            selected = by_ticker[0]
        else:
            # Same ISIN + currency + distribution policy on different venues is
            # the same share class; pick deterministically by ticker.
            tie_pool = by_isin if len(by_isin) > 1 else pool
            isins = {_text(m.get("isin")).upper() for m in tie_pool}
            if len(isins) == 1 and "" not in isins:
                selected = sorted(tie_pool, key=lambda m: _text(m.get("ticker")))[0]
            else:
                return None, f"ambiguous: {len(pool)} listings remain after currency/distribution filters"
    # Prefer the distributing share class of the same fund for cash withdrawal.
    name = _text(selected.get("name"))
    if _text(selected.get("type")).upper() == "ETF" and "(ACC)" in name.upper():
        base = name.upper().replace("(ACC)", "").strip()
        siblings = [
            r for r in catalog
            if _text(r.get("name")).upper() == f"{base} (DIST)"
            and _text(r.get("currencyCode", r.get("currency"))).upper() == account_currency
        ]
        sibling_isins = {_text(r.get("isin")).upper() for r in siblings}
        if siblings and len(sibling_isins) == 1 and "" not in sibling_isins:
            sibling = sorted(siblings, key=lambda r: _text(r.get("ticker")))[0]
            return sibling, f"swapped accumulating {selected.get('ticker')} for distributing {sibling.get('ticker')}"
    return selected, "resolved"


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
            request = result.get("request", {})
            quantity = float(request.get("quantity", result.get("quantity", 0)) or 0)
            arguments = request.get("arguments", {}) if isinstance(request.get("arguments"), dict) else {}
            target_price = request.get("limit_price") or request.get("target_price") or arguments.get("limit_price") or arguments.get("stop_price") or ""
            order_lines.append({
                "ticker": request.get("ticker", result.get("ticker", "")),
                "side": "SELL" if quantity < 0 else "BUY",
                "status": "DRY_RUN",
                "quantity": abs(quantity),
                "limit_price": target_price,
                "order_type": request.get("order_type", ""),
            })
        else:
            # Result may lack a request/readback payload (deterministic broker
            # rejection, floor-missing deferral). Use .get() throughout so the
            # renderer shows it instead of raising KeyError.
            request = result.get("request") or {}
            response = result.get("response") or {}
            qty = result.get("quantity", request.get("quantity"))
            try:
                signed_quantity = float(qty or 0)
            except (TypeError, ValueError):
                signed_quantity = 0.0
            quantity = abs(signed_quantity)
            try:
                limit_price = float(
                    (request.get("limit_price")
                     or request.get("target_price")
                     or result.get("limit_price") or 0)
                )
            except (TypeError, ValueError):
                limit_price = 0.0
            side = result.get("side")
            if not side:
                side = "SELL" if signed_quantity < 0 else "BUY"
            order_lines.append({
                "status": result.get("status", "UNKNOWN"),
                "ticker": request.get("ticker", result.get("ticker", "")),
                "side": side,
                "quantity": quantity,
                "limit_price": limit_price,
                "order_type": request.get("order_type", ""),
                "order_id": response.get("id", ""),
                "reason": result.get("reason", ""),
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


def render_report(state: dict[str, Any], results: list[dict[str, Any]], plan: OrderPlan, research: Any, candles: Any, environment: str, llm_timed_out: bool = False, llm_judgment: str = "Success") -> str:
    try:
        from scripts.t212_telegram_template import render
    except ModuleNotFoundError:
        from t212_telegram_template import render
    values = _report_inputs(state, results, plan, research, candles)
    values["llm_timed_out"] = llm_timed_out
    values["llm_judgment"] = llm_judgment
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


async def run_pipeline(args: argparse.Namespace) -> tuple[str, bool]:
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
            for pos in _records(state.get("fetch_all_open_positions", [])):
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
            llm_judgment = "Success"
            try:
                candidates = call_llm(prompt, args.llm_command)
            except Exception as exc:
                # call_llm already prints a warning to stderr and returns empty list
                # on timeout; record that we fell back to empty candidates
                llm_timed_out = isinstance(exc, subprocess.TimeoutExpired)
                llm_judgment = f"Failed: {str(exc).strip() or exc.__class__.__name__}"
                candidates = []
            # Validate every research candidate against the cached catalogue before
            # it can enter sizing or order execution. Ambiguous matches are
            # disambiguated (account currency + distributing preference) rather
            # than rejected outright.
            account_currency = _text(
                (state.get("fetch_account_info") or {}).get("currencyCode")
                if isinstance(state.get("fetch_account_info"), dict) else ""
            ).upper() or "EUR"
            validated_candidates: list[Candidate] = []
            for candidate in candidates:
                matches = _catalog_matches(catalog, ticker=candidate.ticker, isin=candidate.isin, short_name=candidate.ticker)
                match, note = _resolve_listing(catalog, matches, candidate, account_currency)
                if match is None:
                    print(f"  [t212] rejecting {candidate.ticker}: {note} (match count={len(matches)})", file=sys.stderr)
                    continue
                if note != "resolved":
                    print(f"  [t212] {candidate.ticker}: {note}", file=sys.stderr)
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
                catalog=catalog,
            )
            # Resolve candles for both required sources on every run:
            # existing positions/pending orders plus new research candidates.
            account_instruments = _account_candle_instruments(state, catalog)
            candles = await _resolve_candles(session, new_candidates, plan, account_instruments, catalog)
            buy_results = await execute_orders(
                session, plan, execute=args.execute, candles=candles,
                catalog_records=catalog,
            )
            # Reconcile after buys so a just-filled order can receive its
            # protective exits. If one side of a prior pair filled, cancel its
            # orphaned sibling before creating any new pair.
            exit_state = await collect_state(session) if args.execute else state
            exit_positions = _records(exit_state.get("fetch_all_open_positions", []))
            exit_pending = _records(exit_state.get("fetch_all_orders", []))
            exit_results: list[dict[str, Any]] = []
            if args.execute:
                for order_id in orphan_sell_order_ids(positions=exit_positions, pending_orders=exit_pending):
                    print(f"  [t212] cancelling orphaned exit order id={order_id}", file=sys.stderr)
                    await _mcp_call(session, "cancel_order", {"order_id": order_id})
                    try:
                        readback = await _mcp_call(session, "fetch_order", {"order_id": order_id})
                    except Exception as readback_exc:
                        if "404" in str(readback_exc) or "not found" in str(readback_exc).lower():
                            readback = {"status": "CANCELLED_OR_NOT_FOUND"}
                        else:
                            raise
                    exit_results.append({"status": "CANCELLED_ORPHAN", "order_id": order_id, "readback": readback})
                if exit_results:
                    exit_state = await collect_state(session)
                    exit_positions = _records(exit_state.get("fetch_all_open_positions", []))
                    exit_pending = _records(exit_state.get("fetch_all_orders", []))
            current_prices = _current_position_prices(exit_positions, candles)
            stop_actions = build_stop_loss_actions(
                positions=exit_positions,
                pending_orders=exit_pending,
                current_prices=current_prices,
                stop_loss_pct=args.stop_loss_pct,
            )
            exit_plan = build_protective_exit_plan(
                positions=exit_positions,
                pending_orders=exit_pending,
                take_profit_pct=args.take_profit_pct,
                stop_loss_pct=args.stop_loss_pct,
            )
            # Existing TP orders are evaluated first. If a stop is reached,
            # cancel that TP and market-sell; otherwise leave it untouched.
            exit_results.extend(await execute_stop_loss_actions(session, stop_actions, execute=args.execute))
            exit_results.extend(await execute_protective_exits(session, exit_plan, execute=args.execute))
            # Deterministic carry-over: order-level broker rejections (4xx hard
            # validation) are permanent for that payload; promote them into the
            # plan's rejection block so the rendered report's Next actions list
            # explains which orders the broker rejected instead of silent rows.
            _carry_over_order_rejections(plan, buy_results)
            _carry_over_order_rejections(plan, exit_results)
            results = buy_results + exit_results
            report = render_report(exit_state, results, plan, research, candles, args.environment.upper(), llm_timed_out, llm_judgment)
            candle_issue = isinstance(candles, dict) and any(
                isinstance(data, dict) and not data.get("resolved")
                for key, data in candles.items()
                if key != "pending_orders"
            )
            extraction_status = research.get("extraction", "") if isinstance(research, dict) else ""
            research_issue = (
                str(extraction_status).lower() not in {"succeeded", "success"}
                or llm_judgment != "Success"
                or candle_issue
            )
            notify = (
                research_issue
                or bool(_new_filled_activity(
                    state.get("fetch_recent_activity"), exit_state.get("fetch_recent_activity"),
                ))
                or any(isinstance(result.get("response"), dict) for result in results)
                or any(result.get("status") in ("REJECTED_BY_BROKER", "ERROR") for result in results)
            )
        except BaseException as exc:
            print(f"t212 runner stopped: {exc}", file=sys.stderr)
            report = "[CRON_FAILURE] " + str(exc).replace("\n", " ").strip()
            notify = True
        finally:
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
    # async with block exits here: streams are closed, task group is cleaned up
    return report, notify


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-command", required=True)
    parser.add_argument("--llm-command", required=True, help="command that reads the prompt on stdin and prints JSON")
    parser.add_argument("--deliver-command", help="optional command that reads the rendered report on stdin")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--environment", default=configured_environment())
    parser.add_argument("--take-profit-pct", type=float, default=configured_take_profit_pct(), help="fraction above average fill for the take-profit limit")
    parser.add_argument("--stop-loss-pct", type=float, default=configured_stop_loss_pct(), help="fraction below average fill for the protective stop")
    args = parser.parse_args(argv)
    if not 0 < args.take_profit_pct < 1:
        parser.error("--take-profit-pct must be between 0 and 1")
    if not 0 < args.stop_loss_pct < 1:
        parser.error("--stop-loss-pct must be between 0 and 1")
    if args.execute and args.environment.lower() == "live" and not args.allow_live:
        parser.error("--allow-live is required for live execution")
    loop = asyncio.new_event_loop()
    try:
        # Use async with to properly manage the stdio_client's internal task group
        # The streams stay alive for the entire pipeline execution, and the
        # task group is properly cleaned up when the async with block exits.
        report, notify = loop.run_until_complete(run_pipeline(args))
    finally:
        loop.close()

    # In no-agent cron mode, empty stdout means no Telegram delivery. Normal
    # research cycles stay silent; only writes/fills produce the rendered report.
    if not notify:
        return 0
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
