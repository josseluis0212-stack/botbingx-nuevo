def validate_structure(candles: list, signal: str) -> bool:
    """
    Validates that we are not trading against the macro trend.
    Uses an SMA 50 filter with a 0.5% tolerance.
    """
    if len(candles) < 50:
        return False
        
    closes = [c["close"] for c in candles[-50:]]
    sma_50 = sum(closes) / 50
    current_close = candles[-1]["close"]
    
    if signal == "LONG":
        if current_close < sma_50 * 0.995:
            return False
            
    elif signal == "SHORT":
        if current_close > sma_50 * 1.005:
            return False
            
    return True