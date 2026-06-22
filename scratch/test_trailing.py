import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

# Adjust path to import from app
sys.path.append(".")

from app.core.engine import Engine
from app.logger import logger

class MockBingXClient:
    def __init__(self):
        self.request_calls = []
        self.positions = []
        
    async def get_positions(self):
        return self.positions

    async def _request(self, method, url, params=None, signed=True):
        self.request_calls.append((method, url, params))
        return {"success": True, "code": 0, "data": {}}

class MockOrderExecutor:
    def __init__(self):
        self.update_sl_calls = []

    async def update_sl(self, symbol, side, old_sl_id, new_sl_price, remaining_size):
        self.update_sl_calls.append((symbol, side, old_sl_id, new_sl_price, remaining_size))
        return f"sl_new_{len(self.update_sl_calls)}"

    async def verify_and_restore_protection(self, symbol, trade):
        pass

async def run_test():
    logger.info("=== STARTING TRAILING STOP SIMULATION TEST ===")
    
    engine = Engine()
    engine.running = True
    
    # Setup mocks
    client = MockBingXClient()
    executor = MockOrderExecutor()
    engine.client = client
    engine.executor = executor
    
    symbol = "BTC-USDT"
    
    # 1. Setup trade: Entry = 100, SL = 90, so TP = 120, target_dist = 20
    trade = {
        "side": "LONG",
        "entry_price": 100.0,
        "sl_price": 90.0,
        "tp_price": 120.0,
        "target_distance": 20.0,
        "total_size": 0.1,
        "entry_order_id": "entry_1",
        "sl_order_id": "sl_1",
        "tp1_order_id": "tp_1",
        "filled": True,
        "breakeven_hit": False,
        "trailing_active": False,
        "highest_price": 0.0
    }
    engine.trade_state[symbol] = trade
    
    # Set the mock position returned by get_positions
    position = {
        "symbol": symbol,
        "positionSide": "LONG",
        "positionAmt": "0.1",
        "avgPrice": "100.0",
        "markPrice": "100.0"
    }
    client.positions = [position]
    
    # Test case 1: Price is 100 (0% progress)
    logger.info("Test case 1: Price = 100 (0% progress)")
    await engine._reconcile()
    assert not trade["breakeven_hit"]
    assert not trade["trailing_active"]
    assert len(executor.update_sl_calls) == 0
    
    # Test case 2: Price is 107 (35% progress)
    logger.info("Test case 2: Price = 107 (35% progress)")
    position["markPrice"] = "107.0"
    await engine._reconcile()
    assert not trade["breakeven_hit"]
    assert not trade["trailing_active"]
    assert len(executor.update_sl_calls) == 0
    
    # Test case 3: Price is 109 (45% progress) -> Breakeven should trigger (SL to 104)
    logger.info("Test case 3: Price = 109 (45% progress) -> Breakeven triggers")
    position["markPrice"] = "109.0"
    await engine._reconcile()
    assert trade["breakeven_hit"]
    assert not trade["trailing_active"]
    assert len(executor.update_sl_calls) == 1
    assert trade["sl_price"] == 104.0
    assert executor.update_sl_calls[-1][3] == 104.0 # new sl price
    
    # Test case 4: Price is 107 (35% progress) -> SL should remain 104
    logger.info("Test case 4: Price = 107 (35% progress) -> SL remains 104")
    position["markPrice"] = "107.0"
    await engine._reconcile()
    assert trade["breakeven_hit"]
    assert not trade["trailing_active"]
    assert trade["sl_price"] == 104.0
    assert len(executor.update_sl_calls) == 1 # no new call
    
    # Test case 5: Price is 115 (75% progress) -> Trailing triggers (TP cancel, floor to 110)
    logger.info("Test case 5: Price = 115 (75% progress) -> Trailing triggers")
    position["markPrice"] = "115.0"
    await engine._reconcile()
    assert trade["breakeven_hit"]
    assert trade["trailing_active"]
    assert trade["highest_price"] == 115.0
    assert trade["sl_price"] == 111.0 # Initial trailing SL (Floor is 110, trailing is 111)
    # TP order cancellation request sent
    assert len(client.request_calls) == 1
    assert client.request_calls[0][0] == "DELETE"
    assert client.request_calls[0][2]["orderId"] == "tp_1"
    # SL updated
    assert len(executor.update_sl_calls) == 2
    assert executor.update_sl_calls[-1][3] == 111.0

    # Test case 6: Price is 117 (85% progress) -> Peak is 117. Trailing = 117 - 4 = 113. High > Floor (110) -> SL to 113.
    logger.info("Test case 6: Price = 117 (85% progress) -> SL trails to 113")
    position["markPrice"] = "117.0"
    await engine._reconcile()
    assert trade["highest_price"] == 117.0
    assert trade["sl_price"] == 113.0
    assert len(executor.update_sl_calls) == 3
    assert executor.update_sl_calls[-1][3] == 113.0

    # Test case 7: Price falls to 116 (80% progress) -> Peak remains 117, SL remains 113.
    logger.info("Test case 7: Price falls to 116 (80% progress) -> SL remains 113")
    position["markPrice"] = "116.0"
    await engine._reconcile()
    assert trade["highest_price"] == 117.0
    assert trade["sl_price"] == 113.0
    assert len(executor.update_sl_calls) == 3 # no new call

    # Test case 8: Price goes to 122 (110% progress) -> Peak is 122. Trailing = 122 - 4 = 118. SL to 118.
    logger.info("Test case 8: Price goes to 122 -> SL trails to 118")
    position["markPrice"] = "122.0"
    await engine._reconcile()
    assert trade["highest_price"] == 122.0
    assert trade["sl_price"] == 118.0
    assert len(executor.update_sl_calls) == 4
    assert executor.update_sl_calls[-1][3] == 118.0

    logger.info("=== SHORT SIDE SIMULATION TEST ===")
    
    # 2. Setup SHORT trade: Entry = 100, SL = 110, so TP = 80, target_dist = 20
    trade_short = {
        "side": "SHORT",
        "entry_price": 100.0,
        "sl_price": 110.0,
        "tp_price": 80.0,
        "target_distance": 20.0,
        "total_size": 0.1,
        "entry_order_id": "entry_2",
        "sl_order_id": "sl_2",
        "tp1_order_id": "tp_2",
        "filled": True,
        "breakeven_hit": False,
        "trailing_active": False,
        "highest_price": 0.0
    }
    engine.trade_state[symbol] = trade_short
    
    position_short = {
        "symbol": symbol,
        "positionSide": "SHORT",
        "positionAmt": "-0.1",
        "avgPrice": "100.0",
        "markPrice": "100.0"
    }
    client.positions = [position_short]
    
    # Test case 9: Price is 93 (35% progress)
    logger.info("Test case 9: Price = 93 (35% progress)")
    await engine._reconcile()
    assert not trade_short["breakeven_hit"]
    assert not trade_short["trailing_active"]
    
    # Test case 10: Price is 91 (45% progress) -> Breakeven triggers (SL to 96)
    logger.info("Test case 10: Price = 91 (45% progress) -> Breakeven triggers")
    position_short["markPrice"] = "91.0"
    await engine._reconcile()
    assert trade_short["breakeven_hit"]
    assert not trade_short["trailing_active"]
    assert trade_short["sl_price"] == 96.0

    # Test case 11: Price is 85 (75% progress) -> Trailing triggers (TP cancel, floor to 90)
    logger.info("Test case 11: Price = 85 (75% progress) -> Trailing triggers")
    position_short["markPrice"] = "85.0"
    await engine._reconcile()
    assert trade_short["trailing_active"]
    assert trade_short["highest_price"] == 85.0
    assert trade_short["sl_price"] == 89.0 # Initial trailing SL (Floor is 90, trailing is 89)

    # Test case 12: Price falls to 83 (85% progress) -> SL trails to 83 + 4 = 87. Lower than floor (90) -> SL to 87.
    logger.info("Test case 12: Price falls to 83 -> SL trails to 87")
    position_short["markPrice"] = "83.0"
    await engine._reconcile()
    assert trade_short["highest_price"] == 83.0
    assert trade_short["sl_price"] == 87.0

    logger.info("=== ALL SIMULATION TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    asyncio.run(run_test())
