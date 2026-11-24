#!/usr/bin/env python3
"""
Trading 212 Telegram run-template renderer.

Deterministic: identical inputs always produce the identical template string.
The environment label is read from the Hermes config (mcp_servers.trading212.env),
placed ONLY in the title, and never mentioned in the Account section.

The rendered output uses **bold** for section headings (no ### headings,
no bullet characters, no code fences): the message is exactly the template --
nothing before the title and nothing after the Sources block.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("HERMES_HOME", "/opt/data")) / "config.yaml"


def _read_env_from_config(config_path=CONFIG_PATH):
    """Return the account environment label (demo|live) from the Hermes config."""
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return "unknown (config unreadable: {})".format(exc)
    match = re.search(r"^\s*ENVIRONMENT:\s*(\S+)", text, re.MULTILINE)
    if not match:
        return "unknown"
    return match.group(1).strip()


def _fmt_money(value):
    """Format a euro amount as a deterministic plain string (€X,XXX.XX)."""
    if isinstance(value, str):
        text = value.strip()
        return text if text else "0.00"
    try:
        return "€{:.2f}".format(float(value))
    except (TypeError, ValueError):
        return "0.00"


def _fmt_money_full(value):
    if isinstance(value, str):
        text = value.strip()
        return text if text else "0.00"
    try:
        return "{:.2f}".format(float(value))
    except (TypeError, ValueError):
        return "0.00"


def _orders_block(orders, *, pending=False):
    """Plain-text list of orders, or the 'none placed' line."""
    if not orders:
        return "New: none placed this run."
    lines = []
    for order in orders:
        if isinstance(order, dict):
            status = order.get("status", "" if pending else "")
            if pending and str(status).upper() == "NEW":
                status = "PENDING"
            ticker = _strip_ticker_suffix(order.get("ticker", ""))
            quantity = order.get("quantity", order.get("quantityExecuted", ""))
            limit_price = order.get("limit_price", order.get("limitPrice", ""))
            order_id = order.get("id", order.get("orderId", ""))
            created_at = order.get("created_at", order.get("createdAt"))
            try:
                lp = float(limit_price) if limit_price else 0.0
            except (TypeError, ValueError):
                lp = 0.0
            side = str(order.get("side", "")).upper()
            try:
                numeric_quantity = float(quantity) if quantity else 0.0
            except (TypeError, ValueError):
                numeric_quantity = 0.0
            if not side:
                side = "SELL" if numeric_quantity < 0 else "BUY"
            quantity = abs(numeric_quantity) if numeric_quantity else quantity
            if pending:
                since = f" Since: {created_at[:16] if len(created_at) > 16 else created_at}" if created_at else ""
                lines.append(f"{ticker}: {side} {quantity} @ {lp:.2f} (#{order_id} from {created_at[:16] if created_at else ''})")
            elif created_at:
                created = created_at[:16] if len(created_at) > 16 else created_at
                lines.append(f"{status} {ticker} {side} {quantity} @ €{lp:.2f} (#{order_id} from {created})")
            else:
                lines.append(f"{status} {ticker} {side} {quantity} @ €{lp:.2f} (#{order_id})")
        else:
            lines.append(str(order))
    return "\n".join(lines)


def _strip_ticker_suffix(ticker: str) -> str:
    """Strip the distribution suffix from a Trading 212 ticker.

    Trading 212 ticker suffixes:
      d_EQ / l_EQ = distributing
      m_EQ / a_EQ = accumulating
    Returns the ticker without the distribution suffix.
    """
    if not ticker:
        return ticker
    upper = ticker.upper()
    if not upper.endswith("_EQ"):
        # Already a clean ticker — no suffix to strip
        return ticker
    # Strip the _EQ part to get the raw ticker name (e.g. "VWCEd" from "VWCEd_EQ")
    raw = upper[:upper.rfind("_EQ")]
    # Strip the distribution/accumulation suffix character if present
    if raw and raw[-1] in "DLMA":
        raw = raw[:-1]
    return ticker[:len(raw)] if raw else ticker


def _holdings_block(holdings):
    """Plain-text holdings list, or the 'none' line."""
    if not holdings:
        return "None (0 open positions; 0 filled)."
    lines = []
    for i, h in enumerate(holdings, start=1):
        ticker = h.get("ticker", "?")
        value = _fmt_money_full(h.get("value", 0))
        pct = h.get("pct", 0)
        lines.append("{}. {}: €{} ({:.1f}%)".format(i, ticker, value, pct))
    return "\n".join(lines)


def _next_actions_block(actions):
    """Plain-text action list."""
    if not actions:
        return ""
    return "\n".join(actions)


def _sources_block(sources):
    """Plain-text source attributions."""
    if not sources:
        return ""
    return "\n".join(sources)


def render(env, timestamp, balance, free_cash, invested, pnl, positions,
           orders, pending_orders, next_actions, candles, extraction, sources,
           llm_timed_out=False, llm_judgment="Success"):
    env = env or _read_env_from_config()
    title = "Trading 212 Run ({env}) - {timestamp}".format(env=env, timestamp=timestamp)

    lines = [title, ""]

    lines.append("**Account**")
    lines.append(
        "Balance: {} · Free cash: {} · Invested: {} · P/L: {}".format(
            _fmt_money(balance),
            _fmt_money(free_cash),
            _fmt_money(invested),
            _fmt_money(pnl),
        )
    )
    lines.append("Open positions: {}".format(positions))
    lines.append("**Open orders**")
    if pending_orders:
        lines.append(_orders_block(pending_orders, pending=True))
    else:
        lines.append("None")
    lines.append("")

    lines.append("**Orders this run**")
    if orders:
        lines.append(_orders_block(orders))
    else:
        lines.append("New: none placed this run.")
    lines.append("")

    lines.append("**Next actions**")
    if next_actions:
        lines.append(_next_actions_block(next_actions))
    lines.append("")

    lines.append("**Research**")
    flat_candles = {}
    if isinstance(candles, dict):
        for key, data in candles.items():
            if key == "pending_orders" and isinstance(data, dict):
                flat_candles.update(data)
            else:
                flat_candles[key] = data
    resolved = 0
    candle_issues = []
    for symbol, data in flat_candles.items():
        if isinstance(data, dict) and data.get("resolved"):
            resolved += 1
        else:
            error = data.get("error", "no candle data") if isinstance(data, dict) else str(data)
            candle_issues.append(f"{symbol}: {error}")
    if isinstance(candles, dict):
        lines.append(f"- Candles: resolved for {resolved} ticker{'s' if resolved != 1 else ''}")
    else:
        lines.append(f"- Candles: {candles}")
    if candle_issues:
        lines.append("- Candle issues: " + "; ".join(candle_issues))
    extraction_text = str(extraction)
    lines.append(f"- Extraction: {extraction_text}")
    if extraction_text.lower() not in {"succeeded", "success"}:
        lines.append("- Extraction issue: research extraction did not complete normally")
    lines.append(f"- LLM judgment: {llm_judgment}")
    lines.append("")

    if llm_timed_out:
        lines.append("**LLM selector warning**")
        lines.append("- Warning: the LLM selector timed out after 600 seconds; falling back to empty candidates.")
        lines.append("- This means no new orders could be generated this run. Please re-run a future cycle.")
        lines.append("")

    lines.append("**Sources**")
    if sources:
        lines.append(_sources_block(sources))
    lines.append("")

    return "\n".join(lines)

def _json_list(value):
    if not value:
        return []
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return []


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render the Trading 212 Telegram run template.")
    parser.add_argument("--environment", help="demo or live (defaults to config value)")
    parser.add_argument("--timestamp", required=True, help="run timestamp, e.g. '2026-11-12 09:12 UTC'")
    parser.add_argument("--balance", type=float, required=True)
    parser.add_argument("--free-cash", type=float, required=True)
    parser.add_argument("--invested", type=float, required=True)
    parser.add_argument("--pnl", type=float, required=True)
    parser.add_argument("--positions", type=int, required=True)
    parser.add_argument("--orders", help="JSON list of order strings")
    parser.add_argument("--next-actions", help="JSON list of action strings")
    parser.add_argument("--candles", required=True, help="candle provider status string")
    parser.add_argument("--extraction", required=True, help="extraction status + source string")
    parser.add_argument("--sources", help="JSON list of source attribution strings")
    args = parser.parse_args(argv)

    env = args.environment or _read_env_from_config()
    orders = _json_list(args.orders)
    next_actions = _json_list(args.next_actions)
    sources = _json_list(args.sources)

    output = render(
        env=env,
        timestamp=args.timestamp,
        balance=args.balance,
        free_cash=args.free_cash,
        invested=args.invested,
        pnl=args.pnl,
        positions=args.positions,
        orders=orders,
        positions_list=orders,
        next_actions=next_actions,
        candles=args.candles,
        extraction=args.extraction,
        sources=sources,
    )
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
