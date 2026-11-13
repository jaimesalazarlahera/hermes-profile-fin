import json
import unittest

from scripts.t212_portfolio_automation import (
    Candidate,
    Policy,
    ProposalError,
    UnknownWriteState,
    build_order_plan,
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


class PortfolioPolicyTests(unittest.TestCase):
    def test_duplicate_position_is_rejected_before_sizing(self):
        plan = build_order_plan(
            free_cash=1000,
            positions=[{"ticker": "VWCEd_EQ", "isin": "IE00BK5BQT80", "quantity": 1}],
            pending_orders=[],
            candidates=[candidate()],
            policy=Policy(),
        )
        self.assertEqual(plan.orders, [])
        self.assertTrue(plan.rejections[0].startswith("VWCEd_EQ: duplicate exposure"))

    def test_staged_sizing_keeps_reserve_and_caps_first_tranche(self):
        plan = build_order_plan(
            free_cash=1000,
            positions=[],
            pending_orders=[],
            candidates=[candidate(allocation_pct=0.9, price=100)],
            policy=Policy(reserve_pct=0.1, first_tranche_pct=0.5),
        )
        self.assertEqual(len(plan.orders), 1)
        self.assertEqual(plan.orders[0].quantity, 4.5)
        self.assertEqual(plan.orders[0].notional, 450)
        self.assertEqual(plan.remaining_cash, 450)

    def test_pending_order_matching_is_rejected_even_without_position(self):
        plan = build_order_plan(
            free_cash=1000,
            positions=[],
            pending_orders=[{"ticker": "VWCEd_EQ", "isin": "IE00BK5BQT80", "quantity": 2}],
            candidates=[candidate()],
            policy=Policy(),
        )
        self.assertEqual(plan.orders, [])
        self.assertIn("pending order", plan.rejections[0])

    def test_unknown_write_state_is_distinct_exception(self):
        with self.assertRaises(UnknownWriteState):
            raise UnknownWriteState("place_limit_order returned no parseable order")

    def test_llm_output_requires_exact_json_schema(self):
        with self.assertRaises(ProposalError):
            parse_llm_proposal('{"candidates": [{"ticker": "VWCEd_EQ"}]}')

    def test_llm_output_rejects_extra_or_non_object_candidates(self):
        payload = json.dumps({"candidates": ["VWCEd_EQ"]})
        with self.assertRaises(ProposalError):
            parse_llm_proposal(payload)


if __name__ == "__main__":
    unittest.main()
