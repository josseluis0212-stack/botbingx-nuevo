def check_macro_shock(btc_candle: dict, threshold_pct: float = 0.015) -> bool:
    """
    Escudo Macroeconómico (Anti-Shock)
    Evalúa la vela de 5 minutos de Bitcoin.
    Si (high - low) / close > 1.5%, devuelve True (Bloqueo activado).
    """
    if not btc_candle:
        return False
        
    high = btc_candle.get("high", 0.0)
    low = btc_candle.get("low", 0.0)
    close = btc_candle.get("close", 0.0)
    
    if close <= 0:
        return False
        
    volatility = (high - low) / close
    return volatility > threshold_pct