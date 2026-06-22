import asyncio
from app.exchange.bingx_client import AsyncBingXClient
from app.utils.indicators import calculate_ema, calculate_rsi, calculate_adx, calculate_supertrend

async def test():
    client = AsyncBingXClient()
    symbol = "BTC-USDT"
    
    klines_5m = await client.get_klines(symbol, "5m", 100)
    klines_5m = klines_5m[:-1]
    
    closes = [c["close"] for c in klines_5m]
    highs = [c["high"] for c in klines_5m]
    lows = [c["low"] for c in klines_5m]
    
    ema9 = calculate_ema(closes, 9)[-1]
    ema21 = calculate_ema(closes, 21)[-1]
    ema50 = calculate_ema(closes, 50)[-1]
    
    rsi14 = calculate_rsi(closes, 14)[-1]
    adx14 = calculate_adx(highs, lows, closes, 14)[-1]
    
    supertrend = calculate_supertrend(highs, lows, closes, 10, 3.0)
    st_val = supertrend[-1]["value"]
    st_dir = supertrend[-1]["dir"]
    
    c = klines_5m[-1]
    
    print(f"BTC-USDT DEBUG:")
    print(f"EMA9: {ema9:.2f}, EMA21: {ema21:.2f}, EMA50: {ema50:.2f}")
    print(f"Close: {c['close']}, High: {c['high']}, Low: {c['low']}")
    print(f"ADX: {adx14:.2f} (>20 required)")
    print(f"RSI: {rsi14:.2f} (50-70 LONG, 30-50 SHORT)")
    print(f"Supertrend Dir: {st_dir}")
    print(f"Cond: ema9>ema21 ({ema9>ema21}) and close>ema50 ({c['close']>ema50})")

if __name__ == "__main__":
    asyncio.run(test())
