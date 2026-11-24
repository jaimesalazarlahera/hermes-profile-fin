"""Retry behavior tests for the MCP call layer (mocked, transient failures)."""
import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "t212_portfolio_automation.py"
spec = importlib.util.spec_from_file_location("t212_portfolio_automation", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["t212_portfolio_automation"] = mod
spec.loader.exec_module(mod)


def run(coro):
    return asyncio.run(coro)


class FakeBlock:
    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, blocks):
        self.content = blocks


class FakeSession:
    """Minimal stand-in for the MCP read/write streams used by _mcp_call."""

    def __init__(self, tool_responses):
        self.tool_responses = tool_responses
        self.calls = []

    async def call_tool(self, name, arguments=None):
        self.calls.append(name)
        return FakeResponse(self.tool_responses.pop(0))


class TestMcpcRetry(unittest.TestCase):
    def setUp(self):
        self.saved = getattr(mod, "session", None)

    def tearDown(self):
        if self.saved is None:
            if hasattr(mod, "session"):
                del mod.session
        else:
            mod.session = self.saved

    def make_session(self, responses):
        mod.session = FakeSession(responses)
        return mod.session

    def test_non_json_is_retried_then_returns_proper_result(self):
        session = self.make_session([
            [FakeBlock("not json at all")],                          # transient blip
            [FakeBlock('{"id": "o1", "status": "FILLED"}')],         # valid now
        ])
        result = run(mod._mcp_call(session, "place_limit_order", {}))
        self.assertEqual(session.calls, ["place_limit_order", "place_limit_order"])
        self.assertEqual(result, {"id": "o1", "status": "FILLED"})

    def test_empty_cancel_response_is_success(self):
        session = self.make_session([[]])
        result = run(mod._mcp_call(session, "cancel_order", {"order_id": 60852933285}))
        self.assertIsNone(result)
        self.assertEqual(session.calls, ["cancel_order"])

    def test_non_json_cancel_response_is_treated_as_cleanup_success(self):
        session = self.make_session([[FakeBlock("cancelled")]])
        result = run(mod._mcp_call(session, "cancel_order", {"order_id": 60852933285}))
        self.assertIsNone(result)
        self.assertEqual(session.calls, ["cancel_order"])

    def test_non_json_exhausted_propagates_unknown_writestate(self):
        session = self.make_session([[FakeBlock("<html error page>")]] * 4)  # transient blip, then inert server
        raised = None
        try:
            run(mod._mcp_call(session, "fetch_account_info", {}))
        except mod.UnknownWriteState as exc:
            raised = exc
        self.assertIsNotNone(raised)
        self.assertIn("fetch_account_info", str(raised))
        self.assertIn("non-JSON", str(raised))


if __name__ == "__main__":
    unittest.main()
