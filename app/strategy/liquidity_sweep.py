from app.logger import logger

def detect_sweep(candles):
    """
    Detects Liquidity Sweep pattern based on 17 candles.
    candle 1-15: lookback
    candle 16: sweep
    candle 17: confirm
    """
    if not candles or len(candles) < 17:
        return {"signal": "NONE"}
        
    lookback = candles[:15]
    sweep = candles[15]
    confirm = candles[16]

    # Require sweep to beat 13 out of 15 candles
    # index 2 = 3rd lowest/highest -> 13 candles above/below it
    sorted_lows = sorted([c["low"] for c in lookback])
    sorted_highs = sorted([c["high"] for c in lookback], reverse=True)
    lookback_lows = sorted_lows[2]
    lookback_highs = sorted_highs[2]
    
    # Calculate ATR (Average True Range) using the provided candles
    tr_list = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_list.append(tr)
    atr = sum(tr_list) / len(tr_list) if tr_list else 0
    
    closes = [c["close"] for c in candles]
    from app.utils.indicators import calculate_rsi
    rsi_list = calculate_rsi(closes, 14)
    rsi_val = rsi_list[-2] if rsi_list else 50 # Sweep candle's RSI

    # Calculate wick and body for the sweep candle
    sweep_body = abs(sweep["open"] - sweep["close"])
    sweep_lower_wick = min(sweep["open"], sweep["close"]) - sweep["low"]
    sweep_upper_wick = sweep["high"] - max(sweep["open"], sweep["close"])

    # LONG condition
    # Require strong wick rejection (wick >= 1.5x body) and RSI exhaustion (RSI < 40)
    if sweep["low"] < lookback_lows and confirm["close"] > sweep["low"] and sweep_lower_wick >= sweep_body * 1.5 and rsi_val < 40:
        # Structural SL: Exactly behind the sweep wick
        sl_price = sweep["low"] - (0.1 * atr)
        
        # Structural TP: The opposite side of the local lookback range
        tp_price = sorted_highs[0] # Highest high of the lookback
        
        if tp_price <= confirm["close"]:
            tp_price = confirm["close"] + (1.5 * atr) # Fallback if range is weird
            
        sl_distance_pct = (confirm["close"] - sl_price) / confirm["close"]
        
        # Reject if structural SL is > 2.0% away
        if sl_distance_pct > 0.02:
            return {"signal": "NONE"}
            
        # Minimum distance to avoid getting stopped out by microscopic noise
        if sl_distance_pct < 0.005:
            sl_price = confirm["close"] * 0.995
            
        return {
            "signal": "LONG",
            "entry_price": confirm["close"],
            "sl_price": sl_price,
            "tp1_price": tp_price,
            "tp2_price": 0.0,
            "tp_final_price": tp_price,
            "lock_trigger_price": confirm["close"] + ((tp_price - confirm["close"]) * 0.5), # BE at 50% to target
            "lock_sl_price": confirm["close"] + (0.1 * atr),
            "trailing_dist_atr": 0.0,
            "sweep_low": sweep["low"]
        }
        
    # SHORT condition
    # Require upper wick to be significantly larger than the body to confirm a true rejection
    # Require upper wick to be at least 1.5x the size of the body, and RSI > 60
    if sweep["high"] > lookback_highs and confirm["close"] < sweep["high"] and sweep_upper_wick >= sweep_body * 1.5 and rsi_val > 60:
        # Structural SL: Exactly behind the sweep wick
        sl_price = sweep["high"] + (0.1 * atr)
        
        # Structural TP: The opposite side of the local lookback range
        tp_price = sorted_lows[0] # Lowest low of the lookback
        
        if tp_price >= confirm["close"]:
            tp_price = confirm["close"] - (1.5 * atr) # Fallback
            
        sl_distance_pct = (sl_price - confirm["close"]) / confirm["close"]
        
        # Reject if structural SL is > 2.0% away
        if sl_distance_pct > 0.02:
            return {"signal": "NONE"}
            
        # Minimum distance to avoid microscopic SLs
        if sl_distance_pct < 0.005:
            sl_price = confirm["close"] * 1.005
            
        return {
            "signal": "SHORT",
            "entry_price": confirm["close"],
            "sl_price": sl_price,
            "tp1_price": tp_price,
            "tp2_price": 0.0,
            "tp_final_price": tp_price,
            "lock_trigger_price": confirm["close"] - ((confirm["close"] - tp_price) * 0.5), # BE at 50% to target
            "lock_sl_price": confirm["close"] - (0.1 * atr),
            "trailing_dist_atr": 0.0,
            "sweep_high": sweep["high"]
        }
        
    return {"signal": "NONE"}

async def evaluate_liquidity_sweep(client, symbol: str) -> dict:
    """
    Evaluates the Liquidity Sweep strategy for a given symbol.
    """
    from app.config import Config
    klines = await client.get_klines(symbol, Config.TIMEFRAME, 50)
    if not klines or len(klines) < 17:
        return {"signal": "NONE"}
        
    result = detect_sweep(klines)
    if result["signal"] != "NONE":
        result["strategy"] = "LIQUIDITY_SWEEP"
    return result