import asyncio
import sys
import time

sys.path.insert(0, '.')

from app.core.engine import Engine

class MockBingXClient:
    def __init__(self):
        self.cancelled_symbols = []

    async def cancel_all_orders(self, symbol: str):
        self.cancelled_symbols.append(symbol)
        return True

async def test_close_trade_cleanup():
    print("=== Testing Close Trade Cleanup (Cancel All Orders) ===")
    
    engine = Engine()
    mock_client = MockBingXClient()
    engine.client = mock_client
    
    # Setup trade state
    symbol = "ETH-USDT"
    engine.trade_state[symbol] = {
        "side": "LONG",
        "entry_price": 3000.0,
        "sl_price": 2940.0,
        "total_size": 0.1,
        "filled": True,
        "entry_order_id": "entry_123",
        "sl_order_id": "sl_456",
        "tp1_order_id": "tp_789"
    }
    
    # Call close trade
    await engine._close_trade(symbol, reason="TP_HIT")
    
    # Verify cancel_all_orders was called
    assert symbol in mock_client.cancelled_symbols, "cancel_all_orders was NOT called for symbol!"
    print(f"[PASS] cancel_all_orders was successfully called for {symbol} on close.")
    
    # Verify that trade state was cleared or moved to cooldown
    assert symbol in engine.trade_state, "Symbol state should still exist for cooldown tracking."
    assert "cooldown_until" in engine.trade_state[symbol], "Cooldown was not set on closed symbol."
    assert engine.trade_state[symbol]["cooldown_until"] > time.time(), "Cooldown time is in the past."
    print("[PASS] Trade state correctly transitions to cooldown.")
    
    print("=== Close Trade Cleanup test passed successfully! ===")

if __name__ == "__main__":
    asyncio.run(test_close_trade_cleanup())
