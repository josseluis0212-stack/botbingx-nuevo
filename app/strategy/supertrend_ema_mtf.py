import asyncio
from app.exchange.bingx_client import AsyncBingXClient
from app.utils.indicators import calculate_ema, calculate_atr, calculate_adx, calculate_supertrend
from app.logger import logger

async def analyze(client: AsyncBingXClient, symbol: str) -> dict:
    """
    SuperTrend EMA Regime MTF Pro
    """
    try:
        # Fetch 15m and 1h klines concurrently
        klines_15m, klines_1h = await asyncio.gather(
            client.get_klines(symbol, interval="15m", limit=300),
            client.get_klines(symbol, interval="1h", limit=100)
        )
    except Exception as e:
        logger.error(f"[SUPERTREND_EMA] Error fetching data for {symbol}: {e}")
        return {"signal": "NONE"}

    if not klines_15m or len(klines_15m) < 250 or not klines_1h or len(klines_1h) < 50:
        return {"signal": "NONE"}

    # Extract 15m data
    closes_15m = [k["close"] for k in klines_15m]
    highs_15m = [k["high"] for k in klines_15m]
    lows_15m = [k["low"] for k in klines_15m]
    
    # Calculate 15m indicators
    ema200_15m = calculate_ema(closes_15m, 200)
    ema9_15m = calculate_ema(closes_15m, 9)
    ema21_15m = calculate_ema(closes_15m, 21)
    st_15m = calculate_supertrend(highs_15m, lows_15m, closes_15m, period=10, multiplier=3.0)
    adx_15m = calculate_adx(highs_15m, lows_15m, closes_15m, period=14)
    atr_15m = calculate_atr(highs_15m, lows_15m, closes_15m, period=10)

    # Extract 1h data
    closes_1h = [k["close"] for k in klines_1h]
    
    # Calculate 1h indicators
    ema200_1h = calculate_ema(closes_1h, 200)
    ema9_1h = calculate_ema(closes_1h, 9)
    ema21_1h = calculate_ema(closes_1h, 21)

    # Current values (index -1 is the current forming candle, -2 is the last closed)
    # Using the current forming candle for real-time reactivity as requested, or last closed?
    # Trading systems usually use last closed or current. Let's use current for real-time, but for slopes we use history.
    i = -1
    
    c_price = closes_15m[i]
    c_ema200 = ema200_15m[i]
    c_ema9 = ema9_15m[i]
    c_ema21 = ema21_15m[i]
    c_st_val = st_15m[i]["value"]
    c_st_dir = st_15m[i]["dir"]
    c_adx = adx_15m[i]
    c_atr = atr_15m[i]
    
    # 10 candles ago slope check
    ema200_10_ago = ema200_15m[-11] # -1 is current, -11 is 10 candles ago
    
    c_price_1h = closes_1h[-1]
    c_ema200_1h = ema200_1h[-1]
    c_ema9_1h = ema9_1h[-1]
    c_ema21_1h = ema21_1h[-1]

    # Lookback window for SETUP ARMED (up to 160 candles ago)
    # We scan the past 160 candles (from index -160 to -1)
    setup_long_armed = False
    setup_short_armed = False
    
    for j in range(-161, -1):
        # Condición Previa Bajista -> Arma Long
        if st_15m[j]["dir"] == -1 and closes_15m[j] < ema200_15m[j] and ema9_15m[j] < ema21_15m[j]:
            setup_long_armed = True
            
        # Condición Previa Alcista -> Arma Short
        if st_15m[j]["dir"] == 1 and closes_15m[j] > ema200_15m[j] and ema9_15m[j] > ema21_15m[j]:
            setup_short_armed = True

    signal = "NONE"
    
    # LONG ENTRY CONDITIONS
    if setup_long_armed:
        if (c_st_dir == 1 and 
            c_price > c_ema200 and 
            c_st_val > c_ema200 and 
            c_ema9 > c_ema200 and 
            c_ema21 > c_ema200 and 
            c_ema9 > c_ema21 and 
            c_adx >= 18 and 
            c_ema200 > ema200_10_ago and 
            (c_price - c_ema200) >= (0.3 * c_atr) and 
            c_price_1h > c_ema200_1h and 
            c_ema9_1h > c_ema21_1h):
            signal = "LONG"

    # SHORT ENTRY CONDITIONS
    if setup_short_armed and signal == "NONE":
        if (c_st_dir == -1 and 
            c_price < c_ema200 and 
            c_st_val < c_ema200 and 
            c_ema9 < c_ema200 and 
            c_ema21 < c_ema200 and 
            c_ema9 < c_ema21 and 
            c_adx >= 18 and 
            c_ema200 < ema200_10_ago and 
            (c_ema200 - c_price) >= (0.3 * c_atr) and 
            c_price_1h < c_ema200_1h and 
            c_ema9_1h < c_ema21_1h):
            signal = "SHORT"

    return {
        "signal": signal,
        "entry_price": c_price,
        "atr": c_atr,
        "strategy": "SUPERTREND_EMA_MTF"
    }

def check_exit(trade, client_sync_price=None, klines_15m=None):
    """
    Salida Anticipada por Condición Contraria Completa
    """
    if not klines_15m or len(klines_15m) < 200:
        return False
        
    closes = [k["close"] for k in klines_15m]
    highs = [k["high"] for k in klines_15m]
    lows = [k["low"] for k in klines_15m]
    
    ema200 = calculate_ema(closes, 200)[-1]
    ema9 = calculate_ema(closes, 9)[-1]
    ema21 = calculate_ema(closes, 21)[-1]
    st = calculate_supertrend(highs, lows, closes, period=10, multiplier=3.0)[-1]
    
    price = closes[-1]
    
    if trade.side == "LONG":
        # Condición bajista contraria completa: SuperTrend rojo, todo debajo de EMA200, EMA9 debajo de EMA21
        if (st["dir"] == -1 and 
            price < ema200 and 
            st["value"] < ema200 and 
            ema9 < ema200 and 
            ema21 < ema200 and 
            ema9 < ema21):
            return True
            
    if trade.side == "SHORT":
        # Condición alcista contraria completa: SuperTrend verde, todo encima de EMA200, EMA9 encima de EMA21
        if (st["dir"] == 1 and 
            price > ema200 and 
            st["value"] > ema200 and 
            ema9 > ema200 and 
            ema21 > ema200 and 
            ema9 > ema21):
            return True

    return False
