import json
import unittest

from scripts.t212_portfolio_automation import (
    Candidate,
    OrderPlan,
    PlannedOrder,
    Policy,
    ProposalError,
    UnknownWriteState,
    build_order_plan,
    execute_orders,
    parse_llm_proposal,
)


def candidate(**overrides):
    values = {
        "ticker": "VWCEd_EQ",
        "isin": "IE00BK5BQT80",
        "currency": "EUR",
        "exchange": "XETRA",
        "price": 100.0,
        "allocation_pct": 0.5,
        "rationale": "broad global ETF",
    }
    values.update(overrides)
    return Candidate(**values)


def account_catalog() -> list[dict[str, object]]:
    """Small extract of the account trading catalogue (shape of the live
    instrument cache: ticker, ISIN, type, currency, name, listing id).
    """
    return [
        {
            "ticker": "VWCEd_EQ",
            "isin": "IE00BK5BQT80",
            "type": "ETF",
            "currencyCode": "EUR",
            "name": "Vanguard FTSE All-World (Acc)",
            "workingScheduleId": 166,
        },
        {
            "ticker": "VGWLd_EQ",
            "isin": "IE00B3RBWM25",
            "type": "ETF",
            "currencyCode": "EUR",
            "name": "Vanguard FTSE All-World (Dist)",
            "workingScheduleId": 166,
        },
        {
            "ticker": "VWCEa_EQ",
            "isin": "IE00027FOAR9",
            "type": "STOCK",
            "currencyCode": "EUR",
            "name": "Vanguard FTSE All-World (Acc)",
            "workingScheduleId": 166,
        },
        {
            "ticker": "VBND",
            "isin": "IE00027FOAR9",
            "type": "BOND",
            "currencyCode": "EUR",
            "name": "Vanguard Euro Investment Grade Bond",
            "workingScheduleId": 166,
        },
    ]


class PortfolioPolicyTests(unittest.TestCase):
    def test_duplicate_position_is_rejected_before_sizing(self):
        plan = build_order_plan(
            free_cash=1000,
            positions=[{"ticker": "VWCEd_EQ", "isin": "IE00BK5BQT80", "quantity": 1}],
            pending_orders=[],
            candidates=[candidate()],
            policy=Policy(),
            catalog=account_catalog(),
        )
        self.assertEqual(plan.orders, [])
        self.assertTrue(plan.rejections[0].startswith("VWCEd_EQ: duplicate exposure"))

    def test_staged_sizing_keeps_reserve_and_caps_first_tranche(self):
        plan = build_order_plan(
            free_cash=1000,
            positions=[],
            pending_orders=[],
            candidates=[candidate(allocation_pct=0.9, price=100)],
            policy=Policy(reserve_pct=0.1, first_tranche_pct=0.5, max_allocation_pct=1.0),
            catalog=account_catalog(),
        )
        self.assertEqual(len(plan.orders), 1)
        self.assertEqual(plan.orders[0].quantity, 4.5)
        self.assertEqual(plan.orders[0].notional, 450)
        self.assertEqual(plan.remaining_cash, 450)

    def test_allocation_is_capped_at_twenty_percent(self):
        plan = build_order_plan(
            free_cash=20,
            positions=[],
            pending_orders=[],
            candidates=[candidate(allocation_pct=1.0, price=1)],
            policy=Policy(),
            catalog=account_catalog(),
        )
        self.assertEqual(len(plan.orders), 1)
        self.assertEqual(plan.orders[0].notional, 3.6)

    def test_small_allocation_is_promoted_to_one_euro(self):
        plan = build_order_plan(
            free_cash=20,
            positions=[],
            pending_orders=[],
            candidates=[candidate(allocation_pct=0.01, price=100)],
            policy=Policy(),
            catalog=account_catalog(),
        )
        self.assertEqual(len(plan.orders), 1)
        self.assertEqual(plan.orders[0].quantity, 0.01)
        self.assertEqual(plan.orders[0].notional, 1.0)

    def test_pending_order_matching_is_rejected_even_without_position(self):
        plan = build_order_plan(
            free_cash=1000,
            positions=[],
            pending_orders=[{"ticker": "VWCEd_EQ", "isin": "IE00BK5BQT80", "quantity": 2}],
            candidates=[candidate()],
            policy=Policy(),
            catalog=account_catalog(),
        )
        self.assertEqual(plan.orders, [])
        self.assertIn("pending order", plan.rejections[0])


class ExecuteOrdersBrokerRejectTests(unittest.IsolatedAsyncioTestCase):
    """A rejected-by-broker order must never abort the whole run."""

    async def _run_order_with_responses(self, plan, responses, calls=None):
        if calls is None:
            calls = []

        class _Block:
            def __init__(self, text):
                self.text = text

        class _FakeResponse:
            # A single MCP tool result = one text block whose .text is the raw
            # payload (valid or invalid JSON). Exactly what the MCP server
            # streams back for a tool call.
            def __init__(self, block_text):
                self.content = [_Block(block_text)]

        async def call_tool(name, args=None):
            calls.append(name)
            return _FakeResponse(responses.pop(0))

        session = type("S", (), {})()
        session.call_tool = call_tool
        return await execute_orders(session, plan, execute=True, candles=None)

    async def test_price_too_far_rejection_records_status_and_continues(self):
        from scripts.t212_portfolio_automation import (
            OrderPlan, PlannedOrder, execute_orders,
        )

        plan = OrderPlan(
            orders=[
                PlannedOrder("VWCEd_EQ", "IE00BK5BQT80", 0.02, 153.9,
                             3.078, "broad global ETF"),
                PlannedOrder("IMEUa_EQ", "IE000MAO75G5", 0.32, 6.8152,
                             2.1809, "european core"),
            ],
            rejections=[],
            remaining_cash=100.0,
        )

        # Order 1 (VWCEd_EQ) is rejected by the broker on all four attempts
        # (each attempt a non-JSON payload). Order 2 (IMEUa_EQ) places a valid
        # order on attempt 1; its readback verifies the fill.
        responses = (
            ["not-json-at-all"] * 4
            + ['{"id": 77, "status": "PENDING"}']
            + ['{"id": 77, "status": "PENDING", "ticker": "IMEUa_EQ", "quantity": 0.32}']
        )
        calls, results = [], []
        results = await self._run_order_with_responses(plan, responses, calls)

        self.assertEqual(calls, [
            "place_limit_order", "place_limit_order", "place_limit_order",
            "place_limit_order", "place_limit_order", "fetch_order",
        ])
        self.assertEqual(results[0], {
            "ticker": "VWCEd_EQ", "status": "REJECTED_BY_BROKER",
            "reason": "place_limit_order returned non-JSON data",
            "quantity": 0.02, "limit_price": 153.9,
        })
        self.assertEqual(results[1]["response"]["id"], 77)

    async def test_transient_write_failure_not_aborts_batch(self):
        from scripts.t212_portfolio_automation import (
            OrderPlan, PlannedOrder, execute_orders,
        )

        plan = OrderPlan(
            orders=[PlannedOrder("VWCEd_EQ", "IE00BK5BQT80", 0.02, 153.9,
                                 3.078, "buy")],
            rejections=[],
            remaining_cash=100.0,
        )

        async def fail_call_tool(name, args=None):
            raise Exception("timeout")

        session = type("S", (), {})()
        session.call_tool = fail_call_tool
        results = await execute_orders(session, plan, execute=True, candles=None)
        self.assertEqual(results[0]["status"], "ERROR")
        self.assertIn("timeout", results[0]["reason"])

    async def test_order_below_minimum_tradable_lot_is_rejected_before_broker(self):
        from scripts.t212_portfolio_automation import OrderPlan, PlannedOrder, execute_orders

        # The LIVE account tradable minimum lot for this instrument: 0.09900500
        # shares. A planned 0.05 lot must never reach the broker.
        catalog_records = [
            {
                "ticker": "IWLEq_EQ",
                "isin": "IE000MAO75G5",
                "type": "ETF",
                "currencyCode": "EUR",
                "name": "iShares Core MSCI World (Dist)",
                "workingScheduleId": 166,
                "minTradeQuantity": 0.09900500,
            },
        ]
        plan = OrderPlan(
            orders=[
                PlannedOrder("IWLEq_EQ", "IE000MAO75G5", 0.05, 10.1005,
                             3.0302, "below minimum tradable lot")
            ],
            rejections=[],
            remaining_cash=100.0,
        )

        class _Block:
            def __init__(self, text):
                self.text = text

        class _FakeResponse:
            def __init__(self, block_text):
                self.content = [_Block(block_text)]

        calls = []

        async def call_tool(name, args=None):
            calls.append(name)
            return _FakeResponse('{}')

        session = type("S", (), {})()
        session.call_tool = call_tool
        results = await execute_orders(
            session, plan, execute=True, candles=None,
            catalog_records=catalog_records,
        )

        self.assertEqual(results[0]["status"], "REJECTED_BY_BROKER")
        self.assertIn("minimum tradable lot", results[0]["reason"])
        self.assertEqual(calls, [])  # Lot check happens before any broker call

    async def test_lot_within_limit_places_through_broker(self):
        from scripts.t212_portfolio_automation import OrderPlan, PlannedOrder, execute_orders

        catalog_records = [
            {
                "ticker": "VWCEd_EQ",
                "isin": "IE00BK5BQT80",
                "type": "ETF",
                "currencyCode": "EUR",
                "name": "Vanguard FTSE All-World (Dist)",
                "workingScheduleId": 166,
                "minTradeQuantity": 0.01,
            },
        ]
        plan = OrderPlan(
            orders=[PlannedOrder("VWCEd_EQ", "IE00BK5BQT80", 0.02, 153.9,
                                 3.078, "within minimum tradable lot")],
            rejections=[],
            remaining_cash=100.0,
        )

        class _Block:
            def __init__(self, text):
                self.text = text

        class _FakeResponse:
            def __init__(self, block_text):
                self.content = [_Block(block_text)]

        calls = []

        async def call_tool(name, args=None):
            calls.append(name)
            return _FakeResponse('{"id": 99, "status": "PENDING"}')

        session = type("S", (), {})()
        session.call_tool = call_tool
        results = await execute_orders(
            session, plan, execute=True, candles=None,
            catalog_records=catalog_records,
        )

        self.assertEqual(results[0]["status"], "PLACED")
        self.assertEqual(calls, ["place_limit_order", "fetch_order"])  # read-back verify


class CatalogueCrossReferenceTests(unittest.TestCase):
    """Every order candidate must resolve to exactly one tradable
    catalogue record before sizing touches the broker."""

    def setUp(self):
        from scripts.t212_portfolio_automation import build_order_plan
        self.build_order_plan = build_order_plan

    def test_no_catalogue_record_is_a_deterministic_rejection(self):
        plan = self.build_order_plan(
            free_cash=1000, positions=[], pending_orders=[],
            candidates=[candidate(ticker="VWCEd_XXX", isin="IE0000000000")],
            policy=Policy(), catalog=account_catalog(),
        )
        self.assertEqual(plan.orders, [])
        self.assertTrue(
            plan.rejections[0].startswith(
                "VWCEd_XXX: no instrument catalogue record")
        )

    def test_ambiguous_catalogue_match_is_rejected_before_broker(self):
        # Two catalogue records share one ticker: the candidate must not be
        # sized for the broker when the catalogue itself is ambiguous.
        ambiguous_catalog = [
            {
                "ticker": "VWCEd_EQ",
                "isin": "IE00BK5BQT80",
                "type": "ETF",
                "currencyCode": "EUR",
                "name": "Vanguard FTSE All-World (Acc) - venue A",
                "workingScheduleId": 166,
            },
            {
                "ticker": "VWCEd_EQ",
                "isin": "IE00B3RBWM25",
                "type": "ETF",
                "currencyCode": "EUR",
                "name": "Vanguard FTSE All-World (Acc) - venue B",
                "workingScheduleId": 166,
            },
        ]
        plan = self.build_order_plan(
            free_cash=1000, positions=[], pending_orders=[],
            candidates=[candidate()],
            policy=Policy(), catalog=ambiguous_catalog,
        )
        self.assertEqual(plan.orders, [])
        self.assertTrue(
            any("ambiguous" in r for r in plan.rejections)
        )

    def test_non_orderable_record_is_rejected(self):
        catalog = [
            {
                "ticker": "VBND",
                "isin": "IE00027FOAR9",
                "type": "BOND",
                "currencyCode": "EUR",
                "name": "Vanguard Euro Investment Grade Bond",
                "workingScheduleId": 166,
            },
        ]
        plan = self.build_order_plan(
            free_cash=1000, positions=[], pending_orders=[],
            candidates=[candidate(ticker="VBND", isin="IE00027FOAR9")],
            policy=Policy(), catalog=catalog,
        )
        self.assertEqual(plan.orders, [])
        self.assertTrue(
            plan.rejections[0].startswith("VBND: catalogue record type 'BOND'")
        )

    def test_orderable_record_sized_for_broker(self):
        plan = self.build_order_plan(
            free_cash=20, positions=[], pending_orders=[],
            candidates=[candidate(ticker="VGWLd_EQ", isin="IE00B3RBWM25",
                                  price=157.0, allocation_pct=0.5)],
            policy=Policy(), catalog=account_catalog(),
        )
        self.assertEqual(len(plan.orders), 1)
        self.assertEqual(plan.orders[0].ticker, "VGWLd_EQ")
        self.assertEqual(plan.orders[0].quantity, 0.02)
        self.assertEqual(plan.orders[0].notional, 3.14)


class OrderRejectionCarryOverTests(unittest.TestCase):
    """Order-level broker rejections are carried into the plan rejection
    block so the rendered report's Next actions list the rejected orders."""

    def setUp(self):
        from scripts.t212_portfolio_automation import (
            OrderPlan, PlannedOrder, _carry_over_order_rejections,
        )
        self.OrderPlan = OrderPlan
        self._carry_over = _carry_over_order_rejections

    def test_rejected_buy_is_carried_into_next_actions(self):
        plan = self.OrderPlan(
            orders=[PlannedOrder("VGWLd_EQ", "IE00B3RBWM25", 0.02, 157.0,
                                 3.14, "distributing share")],
            rejections=[],
            remaining_cash=100.0,
        )
        results = [
            {"ticker": "VGWLd_EQ", "status": "REJECTED_BY_BROKER",
             "reason": "place_limit_order returned non-JSON data",
             "quantity": 0.02, "limit_price": 157.0},
            {"ticker": "VUSA", "status": "PLACED",
             "response": {"id": 77, "status": "FILLED"}},
        ]
        plan = self._carry_over(plan, results)
        self.assertEqual(len(plan.rejections), 1)
        self.assertIn("VGWLd_EQ: broker rejected order",
                      plan.rejections[0])

    def test_error_result_is_preserved_as_deterministic_rejection(self):
        plan = self.OrderPlan(orders=[], rejections=["existing"],
                              remaining_cash=100.0)
        results = [{"ticker": "VWCEd_EQ", "status": "ERROR",
                    "reason": "time out after 4 attempts"}]
        plan = self._carry_over(plan, results)
        self.assertTrue(any("VWCEd_EQ: broker rejected order" in r
                            for r in plan.rejections))

    def test_duplicate_rejections_are_deduplicated(self):
        plan = self.OrderPlan(orders=[], rejections=[], remaining_cash=100.0)
        results = [
            {"ticker": "VGWLd_EQ", "status": "REJECTED_BY_BROKER",
             "reason": "instrument can not be traded",
             "quantity": 0.02, "limit_price": 157.0},
            {"ticker": "VGWLd_EQ", "status": "REJECTED_BY_BROKER",
             "reason": "instrument can not be traded",
             "quantity": 0.02, "limit_price": 157.0},
        ]
        plan = self._carry_over(plan, results)
        self.assertEqual(len(plan.rejections), 1)
