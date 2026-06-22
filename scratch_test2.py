import asyncio
from app.exchange.bingx_client import AsyncBingXClient
from app.utils.indicators import calculate_ema, calculate_atr, calculate_adx
from app.config import Config

async def diagnose_symbol(client: AsyncBingXClient, symbol: str):
    klines_15m = await client.get_klines(symbol, Config.TIMEFRAME, 100)
    klines_1h = await client.get_klines(symbol, "1h", 100)
    if not klines_15m or not klines_1h: return
    
    klines_15m = klines_15m[:-1]
    klines_1h = klines_1h[:-1]
    
    closes_15m = [c["close"] for c in klines_15m]
    highs_15m = [c["high"] for c in klines_15m]
    lows_15m = [c["low"] for c in klines_15m]
    closes_1h = [c["close"] for c in klines_1h]
    
    ema100_1h = calculate_ema(closes_1h, 100)[-1]
    adx_list = calculate_adx(highs_15m, lows_15m, closes_15m, 14)
    adx_val = adx_list[-1] if adx_list else 0
    
    c3 = klines_15m[-1]
    c2 = klines_15m[-2]
    c1 = klines_15m[-3]
    
    is_uptrend = c3["close"] > ema100_1h
    is_downtrend = c3["close"] < ema100_1h
    has_strength = adx_val > 20
    
    print(f"--- {symbol} ---")
    print(f"ADX: {adx_val:.2f} (has_strength: {has_strength})")
    print(f"1H Trend: C={c3['close']:.4f} EMA100={ema100_1h:.4f} (up:{is_uptrend} down:{is_downtrend})")
    
    if is_uptrend:
        recent_lows = [k["low"] for k in klines_15m[-43:-3]]
        swing_low = min(recent_lows) if recent_lows else 0
        liquidity_sweep = c1["low"] < swing_low or c2["low"] < swing_low
        bos = c3["close"] > c1["high"] and c3["close"] > c3["open"]
        fvg = c3["low"] > c1["high"]
        print(f"LONG Setup -> Sweep: {liquidity_sweep}, BOS: {bos}, FVG: {fvg}")
    elif is_downtrend:
        recent_highs = [k["high"] for k in klines_15m[-43:-3]]
        swing_high = max(recent_highs) if recent_highs else 0
        liquidity_sweep = c1["high"] > swing_high or c2["high"] > swing_high
        bos = c3["close"] < c1["low"] and c3["close"] < c3["open"]
        fvg = c3["high"] < c1["low"]
        print(f"SHORT Setup -> Sweep: {liquidity_sweep}, BOS: {bos}, FVG: {fvg}")

async def run_test():
    client = AsyncBingXClient()
    for symbol in ["BTC-USDT", "ETH-USDT", "SOL-USDT"]:
        await diagnose_symbol(client, symbol)
    await client.close()

if __name__ == "__main__":
    asyncio.run(run_test())
