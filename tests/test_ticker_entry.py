import asyncio
import sys
import time

sys.path.insert(0, '.')

from app.core.engine import Engine
from app.config import Config

class MockBingXClient:
    def __init__(self, bid=100.0, ask=101.0, last=100.5):
        self.bid = bid
        self.ask = ask
        self.last = last
        self.cancelled_symbols = []
        self.placed_orders = []

    async def get_ticker(self, symbol: str) -> dict:
        return {
            "symbol": symbol.upper(),
            "bidPrice": str(self.bid),
            "askPrice": str(self.ask),
            "lastPrice": str(self.last)
        }

    async def get_balance(self, asset: str = "VST") -> float:
        return 100000.0

    async def set_leverage(self, symbol: str, side: str, leverage: int):
        return True

    async def place_order(self, symbol: str, side: str, position_side: str, order_type: str, quantity: float, price: float = None, stop_price: float = None, post_only: bool = False, reduce_only: bool = False):
        self.placed_orders.append({
            "symbol": symbol,
            "side": side,
            "position_side": position_side,
            "order_type": order_type,
            "quantity": quantity,
            "price": price,
            "post_only": post_only
        })
        return {"success": True, "data": {"orderId": "mock_entry_123"}}

    async def cancel_all_orders(self, symbol: str):
        self.cancelled_symbols.append(symbol)
        return True

    async def get_positions(self, symbol: str = None):
        return []

async def test_ticker_entry():
    print("=== Testing Ticker-Based Limit Order Entry & Validation ===")
    
    engine = Engine()
    mock_client = MockBingXClient(bid=99.5, ask=100.0, last=99.7)
    engine.client = mock_client
    engine.executor.client = mock_client
    
    # 1. Setup mock buffer with 60 candles to pass SMA-50 trend validation
    base_time = int(time.time() * 1000) - 300000 * 65
    
    # First 43 candles: slightly lower prices to keep SMA-50 lower (e.g. close around 99.5)
    mock_candles = [
        {"open": 99.5, "high": 99.7, "low": 99.3, "close": 99.5, "volume": 10, "time": base_time + i * 300000, "closed": True}
        for i in range(43)
    ]
    # Next 15 lookback candles: close around 100.0, high=100.2, low=99.8
    for i in range(43, 58):
        mock_candles.append(
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 10, "time": base_time + i * 300000, "closed": True}
        )
    
    # Sweep candle (index 58): sweeps low=99.0.
    # Open=100.0, Close=99.8 (body=0.2), Low=99.0 (lower wick = min(100, 99.8) - 99.0 = 0.8 >= 0.2)
    sweep_candle = {"open": 100.0, "high": 100.1, "low": 99.0, "close": 99.8, "volume": 10, "time": base_time + 58 * 300000, "closed": True}
    mock_candles.append(sweep_candle)
    
    # Confirm candle (index 59): open=99.8, close=100.0, high=100.2, low=99.8, volume=20
    confirm_candle = {"open": 99.8, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 20, "time": base_time + 59 * 300000, "closed": True}
    mock_candles.append(confirm_candle)
    
    # Add to buffer
    engine.buffers["ETH-USDT"].candles.clear()
    for c in mock_candles:
        engine.buffers["ETH-USDT"].add_candle(c)
        
    # Trigger signal logic for LONG
    await engine._on_closed_candle("ETH-USDT")
    
    # Verify order was placed at bidPrice from ticker (99.5) instead of confirm close (100.0)
    assert len(mock_client.placed_orders) == 1, "Order was not placed! Check signals and trends logs above."
    placed = mock_client.placed_orders[0]
    assert placed["price"] == 99.5, f"Expected entry price 99.5, got {placed['price']}"
    print("[PASS] Limit order placed at the live bidPrice (99.5) rather than confirm close (100.0).")

    # 2. Test SL quality filter > 2.0% validation
    print("\n=== Testing SL > 2% rejection ===")
    mock_client.placed_orders.clear()
    engine.trade_state.clear()
    
    # Let's set bidPrice to 102.0. Structural SL is around 98.775. Dist = 3.16% (> 2%). Should be rejected!
    mock_client.bid = 102.0
    mock_client.ask = 102.5
    mock_client.last = 102.2
    
    engine.buffers["ETH-USDT"].candles.clear()
    for c in mock_candles:
        engine.buffers["ETH-USDT"].add_candle(c)
        
    await engine._on_closed_candle("ETH-USDT")
    assert len(mock_client.placed_orders) == 0, "Order should have been rejected due to SL distance > 2%!"
    print("[PASS] Entry correctly rejected when live SL distance is too large (> 2.0%).")

    # 3. Test SL min distance < 0.5% adjustment
    print("\n=== Testing SL < 0.5% adjustment ===")
    mock_client.placed_orders.clear()
    engine.trade_state.clear()
    
    # Set ticker price close to SL
    # Sweep low = 99.0, atr = ~0.45, so sl_price = 99.0 - 0.225 = 98.775.
    # Set bidPrice to 99.0. Dist = 99.0 - 98.775 = 0.225 (0.22% < 0.5%).
    # Should be adjusted to 99.0 * 0.995 = 98.505.
    mock_client.bid = 99.0
    mock_client.ask = 99.2
    mock_client.last = 99.1
    
    engine.buffers["ETH-USDT"].candles.clear()
    for c in mock_candles:
        engine.buffers["ETH-USDT"].add_candle(c)
        
    await engine._on_closed_candle("ETH-USDT")
    assert len(mock_client.placed_orders) == 1, "Order was not placed!"
    expected_sl = 99.0 * 0.995
    actual_sl = engine.trade_state["ETH-USDT"]["sl_price"]
    assert abs(actual_sl - expected_sl) < 0.0001, f"SL was not adjusted to 0.5%! Expected {expected_sl}, got {actual_sl}"
    print("[PASS] Stop Loss correctly adjusted to maintain minimum 0.5% distance.")

    # 4. Test stale pending entry order timeout (ENTRY_ORDER_MAX_AGE = 180s)
    print("\n=== Testing Stale Entry Order Cancellation ===")
    engine.trade_state["ETH-USDT"] = {
        "side": "LONG",
        "entry_price": 99.0,
        "sl_price": 98.505,
        "total_size": 1.0,
        "filled": False,
        "entry_order_id": "mock_entry_123",
        "timestamp": time.time() - 240
    }
    
    engine.running = True
    await engine._reconcile()
    
    assert "ETH-USDT" in mock_client.cancelled_symbols, "Stale entry order was not cancelled!"
    assert "cooldown_until" in engine.trade_state["ETH-USDT"], "State did not transition to cooldown!"
    print("[PASS] Stale pending entry order successfully cancelled after timeout.")

    print("\n=== All Ticker Entry tests passed successfully! ===")

if __name__ == "__main__":
    asyncio.run(test_ticker_entry())
