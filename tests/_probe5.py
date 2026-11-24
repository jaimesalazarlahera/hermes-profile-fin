import asyncio, sys, traceback
sys.path.insert(0, 'tests')
sys.path.insert(0, 'scripts')
import t212_portfolio_automation as m

# Replica of the failing test's helper + fixture
class Block:
    def __init__(self, text): self.text = text

class FakeResp:
    def __init__(self, blocks):
        self.content = [Block(b) if isinstance(b, dict) else b for b in blocks]

calls = []
responses = (
    [{"text": "not-json-at-all"} for _ in range(4)]
    + [{"text": '{"id": 77, "status": "PENDING"}'}]
    + [{"text": '{"id": 77, "status": "PENDING", "ticker": "IMEUa_EQ", "quantity": 0.32}'}]
)

async def call_tool(name, args=None):
    calls.append(name)
    print('  call_tool ->', name)
    return FakeResp(responses.pop(0))

class S:
    def __init__(self):
        self.calls = []
        self.call_tool = call_tool

plan = m.OrderPlan(
    orders=[m.PlannedOrder("VWCEd_EQ", "IE00BK5BQT80", 0.02, 153.9, 3.078, "a")],
    rejections=[], remaining_cash=100.0,
)
session = S()
try:
    r = await m.execute_orders(session, plan, execute=True, candles=None)
    print('results:', r)
except Exception:
    traceback.print_exc()
print('calls:', session.calls)
