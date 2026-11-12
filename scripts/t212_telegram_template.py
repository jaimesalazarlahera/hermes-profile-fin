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
import re
import sys

CONFIG_PATH = "/opt/data/profiles/poe/config.yaml"


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


def _orders_block(orders):
    """Plain-text list of orders, or the 'none placed' line."""
    if not orders:
        return "New: none placed this run."
    return "\n".join(orders)


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
           orders, holdings, next_actions, candles, extraction, sources):
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
    lines.append("")

    lines.append("**Orders this run**")
    if orders:
        lines.append(_orders_block(orders))
    else:
        lines.append("New: none placed this run.")
    lines.append("")

    lines.append("**Top holdings by value**")
    if holdings:
        lines.append(_holdings_block(holdings))
    else:
        lines.append("None (0 open positions; 0 filled).")
    lines.append("")

    lines.append("**Next actions**")
    if next_actions:
        lines.append(_next_actions_block(next_actions))
    lines.append("")

    lines.append("**Data quality**")
    lines.append("Candles: {}".format(candles))
    lines.append("Extraction: {}".format(extraction))
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
    parser.add_argument("--holdings", help="JSON list of {ticker,value,pct} objects")
    parser.add_argument("--next-actions", help="JSON list of action strings")
    parser.add_argument("--candles", required=True, help="candle provider status string")
    parser.add_argument("--extraction", required=True, help="extraction status + source string")
    parser.add_argument("--sources", help="JSON list of source attribution strings")
    args = parser.parse_args(argv)

    env = args.environment or _read_env_from_config()
    orders = _json_list(args.orders)
    holdings = _json_list(args.holdings)
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
        holdings=holdings,
        next_actions=next_actions,
        candles=args.candles,
        extraction=args.extraction,
        sources=sources,
    )
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
