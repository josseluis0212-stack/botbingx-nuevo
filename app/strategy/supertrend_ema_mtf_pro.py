import asyncio
from app.exchange.bingx_client import AsyncBingXClient
from app.utils.indicators import calculate_ema, calculate_atr, calculate_adx, calculate_supertrend
from app.logger import logger

async def analyze(client: AsyncBingXClient, symbol: str) -> dict:
    """
    SuperTrend EMA Regime MTF Pro
    """
    try:
        klines_15m, klines_1h = await asyncio.gather(
            client.get_klines(symbol, interval="15m", limit=300),
            client.get_klines(symbol, interval="1h", limit=100)
        )
    except Exception as e:
        logger.error(f"[SUPERTREND_EMA_PRO] Error fetching data for {symbol}: {e}")
        return {"signal": "NONE"}

    if not klines_15m or len(klines_15m) < 250 or not klines_1h or len(klines_1h) < 50:
        return {"signal": "NONE"}

    closes_15m = [k["close"] for k in klines_15m]
    highs_15m = [k["high"] for k in klines_15m]
    lows_15m = [k["low"] for k in klines_15m]
    
    ema200 = calculate_ema(closes_15m, 200)
    ema9 = calculate_ema(closes_15m, 9)
    ema21 = calculate_ema(closes_15m, 21)
    st = calculate_supertrend(highs_15m, lows_15m, closes_15m, period=10, multiplier=3.0)
    adx = calculate_adx(highs_15m, lows_15m, closes_15m, period=14)
    atr = calculate_atr(highs_15m, lows_15m, closes_15m, period=10)

    closes_1h = [k["close"] for k in klines_1h]
    ema200_1h = calculate_ema(closes_1h, 200)
    ema9_1h = calculate_ema(closes_1h, 9)
    ema21_1h = calculate_ema(closes_1h, 21)

    c_price = closes_15m[-1]
    c_ema200 = ema200[-1]
    c_ema9 = ema9[-1]
    c_ema21 = ema21[-1]
    c_st_val = st[-1]["value"]
    c_st_dir = st[-1]["dir"]
    c_adx = adx[-1]
    c_atr = atr[-1]
    
    ema200_10_ago = ema200[-11]
    
    c_price_1h = closes_1h[-1]
    c_ema200_1h = ema200_1h[-1]
    c_ema9_1h = ema9_1h[-1]
    c_ema21_1h = ema21_1h[-1]

    # SCAN LAST 160 BARS FOR ARMED STATE
    setup_long_armed = False
    setup_short_armed = False
    
    for j in range(-161, -1):
        # Bearish Prior -> Arms LONG
        if st[j]["dir"] == -1 and closes_15m[j] < ema200[j] and ema9[j] < ema21[j]:
            setup_long_armed = True
            
        # Bullish Prior -> Arms SHORT
        if st[j]["dir"] == 1 and closes_15m[j] > ema200[j] and ema9[j] > ema21[j]:
            setup_short_armed = True

    signal = "NONE"
    
    # LONG ENTRY FILTERS
    adx_ok = c_adx >= 18
    slope_long_ok = (c_ema200 - ema200_10_ago) > 0
    slope_short_ok = (c_ema200 - ema200_10_ago) < 0
    distance_ok = abs(c_price - c_ema200) >= (c_atr * 0.3)
    
    htf_long_ok = c_price_1h > c_ema200_1h and c_ema9_1h > c_ema21_1h
    htf_short_ok = c_price_1h < c_ema200_1h and c_ema9_1h < c_ema21_1h

    if setup_long_armed:
        if (c_st_dir == 1 and 
            c_price > c_ema200 and 
            c_st_val > c_ema200 and 
            c_ema9 > c_ema200 and 
            c_ema21 > c_ema200 and 
            c_ema9 > c_ema21 and 
            adx_ok and slope_long_ok and distance_ok and htf_long_ok):
            signal = "LONG"

    if setup_short_armed and signal == "NONE":
        if (c_st_dir == -1 and 
            c_price < c_ema200 and 
            c_st_val < c_ema200 and 
            c_ema9 < c_ema200 and 
            c_ema21 < c_ema200 and 
            c_ema9 < c_ema21 and 
            adx_ok and slope_short_ok and distance_ok and htf_short_ok):
            signal = "SHORT"

    return {
        "signal": signal,
        "entry_price": c_price,
        "atr": c_atr,
        "strategy": "SUPERTREND_EMA_MTF_PRO"
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
