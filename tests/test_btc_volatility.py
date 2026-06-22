import asyncio
import os
import sys
import time

sys.path.insert(0, '.')

from app.core.engine import Engine
from app.config import Config
from app.constants import BTC_BLOCK_FILE

async def test_btc_volatility():
    print("=== Testing BTC Volatility Block (15m Cumulative Only) ===")
    
    # 1. Clean up old block file
    if os.path.exists(BTC_BLOCK_FILE):
        os.remove(BTC_BLOCK_FILE)
        
    engine = Engine()
    engine.running = True
    
    # Create normal candles
    base_time = int(time.time() * 1000) - 300000 * 5
    normal_candles = [
        {"open": 60000, "high": 60100, "low": 59950, "close": 60050, "volume": 10, "time": base_time + i * 300000, "closed": True}
        for i in range(5)
    ]
    
    # Last candle is live/open
    normal_candles[-1]["closed"] = False
    
    # Feed normal candles
    for c in normal_candles:
        engine.buffers["BTC-USDT"].add_candle(c)
        
    # Check volatility - should NOT block
    await engine._check_btc_volatility("BTC-USDT")
    assert engine.btc_blocked_until < time.time(), f"Engine blocked incorrectly: {engine.btc_block_reason}"
    print("[PASS] Normal candles did not trigger a block.")
    
    # 2. Test live candle volatility spike (should NOT block now)
    live_candle = dict(normal_candles[-1])
    live_candle["close"] = live_candle["open"] * 0.97 # 3% drop
    engine.buffers["BTC-USDT"].add_candle(live_candle)
    
    await engine._check_btc_volatility("BTC-USDT")
    assert engine.btc_blocked_until < time.time(), "Engine blocked incorrectly on live candle!"
    print("[PASS] Live candle spike did not block (as expected under the new 15m rule).")
    
    # 3. Test closed candle volatility spike (should NOT block now)
    normal_candles = [
        {"open": 60000, "high": 60100, "low": 59950, "close": 60050, "volume": 10, "time": base_time + i * 300000, "closed": True}
        for i in range(5)
    ]
    # Make closed candle (second to last) have range > 2.5%
    normal_candles[-2]["high"] = 61500 # 2.58% range
    normal_candles[-1]["closed"] = False
    
    engine.buffers["BTC-USDT"].candles.clear()
    for c in normal_candles:
        engine.buffers["BTC-USDT"].add_candle(c)
        
    await engine._check_btc_volatility("BTC-USDT")
    assert engine.btc_blocked_until < time.time(), "Engine blocked incorrectly on single closed candle!"
    print("[PASS] Single closed candle range spike did not block (as expected under the new 15m rule).")
    
    # 4. Test cumulative 3-candle body change spike (> 1.5%)
    normal_candles = [
        {"open": 60000, "high": 60100, "low": 59950, "close": 60050, "volume": 10, "time": base_time + i * 300000, "closed": True}
        for i in range(5)
    ]
    # Candle -4 open: 60000, Candle -2 close: 61000 (change = 1.67%, which is > 1.5% threshold)
    normal_candles[-4]["open"] = 60000
    normal_candles[-4]["close"] = 60300
    normal_candles[-3]["open"] = 60300
    normal_candles[-3]["close"] = 60600
    normal_candles[-2]["open"] = 60600
    normal_candles[-2]["close"] = 61000
    normal_candles[-1]["closed"] = False
    
    engine.buffers["BTC-USDT"].candles.clear()
    for c in normal_candles:
        engine.buffers["BTC-USDT"].add_candle(c)
        
    await engine._check_btc_volatility("BTC-USDT")
    assert engine.btc_blocked_until > time.time(), "Engine failed to block on 15m cumulative change spike!"
    print(f"[PASS] Cumulative body change spike successfully blocked. Reason: {engine.btc_block_reason}")
    assert os.path.exists(BTC_BLOCK_FILE), "Block file was not written!"
    print("[PASS] Block state successfully persisted to file.")
    
    # Clean up test files
    if os.path.exists(BTC_BLOCK_FILE):
        os.remove(BTC_BLOCK_FILE)
        
    print("=== All tests passed successfully! ===")

if __name__ == "__main__":
    asyncio.run(test_btc_volatility())
