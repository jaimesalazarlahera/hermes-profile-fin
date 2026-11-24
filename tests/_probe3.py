import sys
sys.path.insert(0, 'scripts')
import t212_portfolio_automation as m

class Block:
    def __init__(self, text):
        self.text = text

class FakeResp:
    def __init__(self, blocks):
        self.content = [Block(b) if isinstance(b, dict) else b for b in blocks]

calls = []
responses = (
    [[{"text": "not-json-at-all"}] for _ in range(4)]
    + [[{"text": '{"id": 77, "status": "PENDING"}'}]]
    + [[{"text": '{"id": 77, "status": "PENDING", "ticker": "IMEUa_EQ", "quantity": 0.32}'}]]
)

async def call_tool(name, args=None):
    calls.append(name)
    return FakeResp(responses.pop(0))

class S:
    def __init__(self):
        self.calls = []
        self.call_tool = call_tool

plan = m.OrderPlan(
    orders=[
        m.PlannedOrder("VWCEd_EQ", "IE00BK5BQT80", 0.02, 153.9, 3.078, "a"),
        m.PlannedOrder("IMEUa_EQ", "IE000MAO75G5", 0.32, 6.8152, 2.1809, "b"),
    ],
    rejections=[], remaining_cash=100.0,
)

import asyncio
async def main():
    session = S()
    print('session:', session)
    print('call_tool is S.call_tool:', session.call_tool)
    r = await m.execute_orders(session, plan, execute=True, candles=None)
    print('calls:', calls)
    print('results:', r)

asyncio.run(main())
