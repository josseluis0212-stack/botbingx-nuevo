import sys
import os

# Add the project directory to the path so we can import app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.strategy.liquidity_sweep import detect_sweep

def test_lrmc_pro_sweep_long():
    candles = []
    
    # 1. Creates an array of 17 mock candles
    # 2. First 15 candles have lows around 50000
    for i in range(15):
        candles.append({
            "low": 50000.0,
            "high": 50500.0,
            "open": 50200.0,
            "close": 50300.0,
            "timestamp": i
        })
        
    # 3. The 16th candle (sweep) should drop to 49500
    candles.append({
        "low": 49500.0,
        "high": 50000.0,
        "open": 49900.0,
        "close": 49600.0,
        "timestamp": 15
    })
    
    # 4. The 17th candle (confirm) should close above 49500 (e.g., 49800)
    candles.append({
        "low": 49400.0, # low doesn't matter for the LONG condition after sweep
        "high": 49900.0,
        "open": 49600.0,
        "close": 49800.0,
        "timestamp": 16
    })
    
    # 5. Pass to detect_sweep and assert
    result = detect_sweep(candles)
    
    print("Result:", result)
    
    assert result["signal"] == "LONG", f"Expected LONG, got {result['signal']}"
    
    expected_sl = 49500.0 * 0.995
    assert result["sl_price"] == expected_sl, f"Expected SL {expected_sl}, got {result['sl_price']}"
    
    print("Test passed successfully!")

if __name__ == "__main__":
    test_lrmc_pro_sweep_long()
