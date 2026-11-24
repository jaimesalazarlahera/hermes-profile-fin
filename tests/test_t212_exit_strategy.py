import importlib.util
import sys
from pathlib import Path


SCRIPT = Path("/opt/data/profiles/fin/scripts/t212_portfolio_automation.py")
spec = importlib.util.spec_from_file_location("t212_portfolio_automation", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules["t212_portfolio_automation"] = module
spec.loader.exec_module(module)


def test_take_profit_uses_average_fill_and_actual_position_quantity():
    plan = module.build_take_profit_plan(
        positions=[{"ticker": "AAPL_US_EQ", "quantity": 3.0, "averagePrice": 100.1234}],
        pending_orders=[],
        take_profit_pct=0.02,
    )

    assert len(plan) == 1
    assert plan[0].ticker == "AAPL_US_EQ"
    assert plan[0].quantity == -3.0
    assert plan[0].limit_price == 102.1259
    assert plan[0].fill_price == 100.1234


def test_take_profit_does_not_duplicate_existing_sell_order():
    plan = module.build_take_profit_plan(
        positions=[{"ticker": "AAPL_US_EQ", "quantity": 3.0, "averagePrice": 100.0}],
        pending_orders=[{"ticker": "AAPL_US_EQ", "quantity": -3.0, "status": "NEW"}],
        take_profit_pct=0.02,
    )

    assert plan == []


def test_protective_plan_creates_take_profit_only():
    plan = module.build_protective_exit_plan(
        positions=[{"ticker": "AAPL_EU_EQ", "quantity": 3.0, "averagePrice": 100.0}],
        pending_orders=[],
        take_profit_pct=0.03,
        stop_loss_pct=0.015,
    )
    assert len(plan) == 1
    assert plan[0].ticker == "AAPL_EU_EQ"
    assert plan[0].quantity == -3.0
    assert plan[0].limit_price == 103.0
    assert plan[0].fill_price == 100.0


def test_stop_action_triggers_only_at_or_below_threshold():
    actions = module.build_stop_loss_actions(
        positions=[{"ticker": "AAPL_EU_EQ", "quantity": 3.0, "averagePrice": 100.0}],
        pending_orders=[{"ticker": "AAPL_EU_EQ", "quantity": -3.0, "side": "SELL", "type": "LIMIT", "id": 44, "limitPrice": 103.0}],
        current_prices={"AAPL_EU_EQ": 98.5},
        stop_loss_pct=0.015,
    )
    assert len(actions) == 1
    assert actions[0].take_profit_order_id == 44
    assert actions[0].quantity == -3.0
    assert actions[0].stop_price == 98.5


def test_stop_action_leaves_take_profit_above_threshold():
    actions = module.build_stop_loss_actions(
        positions=[{"ticker": "AAPL_EU_EQ", "quantity": 3.0, "averagePrice": 100.0}],
        pending_orders=[{"ticker": "AAPL_EU_EQ", "quantity": -3.0, "side": "SELL", "type": "LIMIT", "id": 44, "limitPrice": 103.0}],
        current_prices={"AAPL_EU_EQ": 99.0},
        stop_loss_pct=0.015,
    )
    assert actions == []


def test_protective_plan_skips_position_with_existing_sell():
    plan = module.build_protective_exit_plan(
        positions=[{"ticker": "AAPL_EU_EQ", "quantity": 3.0, "averagePrice": 100.0}],
        pending_orders=[{"ticker": "AAPL_EU_EQ", "quantity": -3.0, "side": "SELL"}],
        take_profit_pct=0.03,
        stop_loss_pct=0.015,
    )
    assert plan == []


def test_orphan_sell_is_detected_after_position_closes():
    ids = module.orphan_sell_order_ids(
        positions=[],
        pending_orders=[{"ticker": "AAPL_EU_EQ", "quantity": -3.0, "id": 123}],
    )
    assert ids == [123]


VWCE_ACC = {"ticker": "VWCEd_EQ", "name": "Vanguard FTSE All-World (Acc)", "type": "ETF", "currencyCode": "EUR", "isin": "IE00BK5BQT80", "shortName": "VWCE"}
VWRL_EUR = {"ticker": "VWRLa_EQ", "name": "Vanguard FTSE All-World (Dist)", "type": "ETF", "currencyCode": "EUR", "isin": "IE00B3RBWM25", "shortName": "VWRL"}
VGWL_EUR = {"ticker": "VGWLd_EQ", "name": "Vanguard FTSE All-World (Dist)", "type": "ETF", "currencyCode": "EUR", "isin": "IE00B3RBWM25", "shortName": "VGWL"}
VWRL_GBP = {"ticker": "VWRLl_EQ", "name": "Vanguard FTSE All-World (Dist)", "type": "ETF", "currencyCode": "GBP", "isin": "IE00B3RBWM25", "shortName": "VWRL"}
VWRL_CHF = {"ticker": "VWRLs_EQ", "name": "Vanguard FTSE All-World (Dist)", "type": "ETF", "currencyCode": "CHF", "isin": "IE00B3RBWM25", "shortName": "VWRL"}


def test_ambiguous_vwce_resolves_to_eur_distributing_listing():
    catalog = [VWCE_ACC, VWRL_EUR, VGWL_EUR, VWRL_GBP, VWRL_CHF]
    candidate = module.Candidate(
        ticker="VWCE", isin="IE00B3RBWM25", currency="EUR", exchange="XETRA",
        price=100.0, allocation_pct=0.1, rationale="mixed identity from research",
    )
    matches = module._catalog_matches(catalog, ticker="VWCE", isin=candidate.isin, short_name="VWCE")
    assert len(matches) == 5
    selected, note = module._resolve_listing(catalog, matches, candidate, "EUR")
    assert selected is not None
    # Two EUR venues for the same Dist ISIN: deterministic ticker tie-break.
    assert selected["ticker"] == "VGWLd_EQ"
    assert selected["isin"] == "IE00B3RBWM25"


def test_single_accumulating_etf_swaps_to_distributing_sibling():
    catalog = [VWCE_ACC, VWRL_EUR]
    candidate = module.Candidate(
        ticker="VWCEd_EQ", isin="IE00BK5BQT80", currency="EUR", exchange="XETRA",
        price=100.0, allocation_pct=0.1, rationale="acc proposal",
    )
    matches = module._catalog_matches(catalog, ticker=candidate.ticker, isin=candidate.isin, short_name=candidate.ticker)
    assert len(matches) == 1
    selected, note = module._resolve_listing(catalog, matches, candidate, "EUR")
    assert selected["ticker"] == "VWRLa_EQ"
    assert "swapped" in note


def test_unresolvable_ambiguity_is_rejected():
    # Same shortName/currency but DIFFERENT ISINs = genuinely different funds.
    other_fund = dict(VWRL_EUR, ticker="VWRLx_EQ", isin="IE00OTHER001")
    catalog = [VWRL_EUR, other_fund]
    candidate = module.Candidate(
        ticker="VWRL", isin="", currency="EUR", exchange="AEB",
        price=100.0, allocation_pct=0.1, rationale="ambiguous",
    )
    matches = module._catalog_matches(catalog, ticker="VWRL", isin="", short_name="VWRL")
    selected, note = module._resolve_listing(catalog, matches, candidate, "EUR")
    assert selected is None
    assert "ambiguous" in note


def test_same_isin_different_venues_tie_breaks_deterministically():
    catalog = [VWRL_EUR, VGWL_EUR]
    candidate = module.Candidate(
        ticker="VWRL", isin="IE00B3RBWM25", currency="EUR", exchange="AEB",
        price=100.0, allocation_pct=0.1, rationale="two venues",
    )
    matches = module._catalog_matches(catalog, ticker="VWRL", isin=candidate.isin, short_name="VWRL")
    selected, note = module._resolve_listing(catalog, matches, candidate, "EUR")
    assert selected is not None
    assert selected["ticker"] == "VGWLd_EQ"


def test_buy_plan_rejects_non_eur_settlement_currency():
    candidate = module.Candidate(
        ticker="AAPL_US_EQ",
        isin="US0378331005",
        currency="USD",
        exchange="NASDAQ",
        price=100.0,
        allocation_pct=0.10,
        rationale="test",
    )

    plan = module.build_order_plan(
        free_cash=1000.0,
        positions=[],
        pending_orders=[],
        candidates=[candidate],
        policy=module.Policy(),
    )

    assert plan.orders == []
    assert "AAPL_US_EQ: non-EUR candidate" in plan.rejections
