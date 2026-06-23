from app.utils.indicators import calculate_ema, calculate_sma, calculate_atr, calculate_adx, calculate_rsi
from app.config import Config

async def evaluate_bustos_pullback(client, symbol: str) -> dict:
    """
    Estrategia "Riesgo 99.9% Eliminado" (Federico Bustos)
    - Trend: 1H > EMA 100
    - Strength: ADX > 20 en 15m
    - Trigger: 15m pullback tocando EMA 21
    - Riesgo: Stop Loss debajo de SMA 50
    - TP: Último máximo (con RR > 1)
    """
    # 1. Macro Trend (1H)
    klines_1h = await client.get_klines(symbol, "1h", 100)
    if not klines_1h or len(klines_1h) < 100: return {"signal": "NONE"}
    closes_1h = [c["close"] for c in klines_1h]
    ema100_1h = calculate_ema(closes_1h, 100)[-1]
    current_close_1h = closes_1h[-1]
    
    bias = "LONG" if current_close_1h > ema100_1h else "SHORT"
    
    # 2. Ejecución (15M)
    klines_15m = await client.get_klines(symbol, Config.TIMEFRAME, 60)
    if not klines_15m or len(klines_15m) < 55: return {"signal": "NONE"}
    
    closes_15m = [c["close"] for c in klines_15m]
    highs_15m = [c["high"] for c in klines_15m]
    lows_15m = [c["low"] for c in klines_15m]
    
    ema21_15m = calculate_ema(closes_15m, 21)
    sma50_15m = calculate_sma(closes_15m, 50)[-1]
    
    # Calculate ATR, Volume SMA, and ADX
    atr_15m = calculate_atr(highs_15m, lows_15m, closes_15m, 14)[-1]
    
    adx_list = calculate_adx(highs_15m, lows_15m, closes_15m, 14)
    adx_val = adx_list[-1] if adx_list else 0
    has_strength = adx_val > 20
    
    rsi_list = calculate_rsi(closes_15m, 14)
    rsi_val = rsi_list[-1] if rsi_list else 50
    
    volumes_15m = [c["volume"] for c in klines_15m]
    sma_vol_10 = calculate_sma(volumes_15m, 10)[-1]
    
    current_ema21 = ema21_15m[-1]
    old_ema21 = ema21_15m[-4] if len(ema21_15m) >= 4 else ema21_15m[-1]
    
    c = klines_15m[-1]  # La vela que acaba de cerrar
    
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    signal = "NONE"
    
    if not has_strength:
        return {"signal": "NONE"}
    
    if bias == "LONG":
        # Condición de tendencia en 15M: EMA 21 por encima de SMA 50 y pendiente positiva
        if current_ema21 > sma50_15m and current_ema21 > old_ema21:
            # Pullback a la EMA 21 con rechazo alcista y volumen alto
            if c["low"] <= current_ema21 and c["close"] > current_ema21 and c["close"] > c["open"] and c["volume"] > sma_vol_10:
                if rsi_val < 65: # Prevent buying when locally overbought
                    entry_price = c["close"]  # Entramos al mercado inmediatamente
                sl_price = sma50_15m - (atr_15m * 1.5)  # SL adaptativo debajo de la SMA 50
                
                # Buscar el máximo reciente (Take Profit)
                recent_high = max(highs_15m[-20:])
                
                # Verificar asimetría (Risk/Reward mínimo de 1:1)
                risk = entry_price - sl_price
                reward = recent_high - entry_price
                
                if risk > 0 and reward >= risk:
                    tp_price = recent_high
                    signal = "LONG"
    else:
        # Condición de tendencia bajista en 15M: EMA 21 por debajo de SMA 50 y pendiente negativa
        if current_ema21 < sma50_15m and current_ema21 < old_ema21:
            # Pullback a la EMA 21 con rechazo bajista y volumen alto
            if c["high"] >= current_ema21 and c["close"] < current_ema21 and c["close"] < c["open"] and c["volume"] > sma_vol_10:
                if rsi_val > 35: # Prevent shorting when locally oversold
                    entry_price = c["close"]
                sl_price = sma50_15m + (atr_15m * 1.5)  # SL adaptativo encima de la SMA 50
                
                # Buscar el mínimo reciente (Take Profit)
                recent_low = min(lows_15m[-20:])
                
                risk = sl_price - entry_price
                reward = entry_price - recent_low
                
                if risk > 0 and reward >= risk:
                    tp_price = recent_low
                    signal = "SHORT"
                    
    if signal != "NONE":
        return {
            "signal": signal,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "atr": atr_15m,
            "strategy": "BUSTOS_PULLBACK"
        }
        
    return {"signal": "NONE"}
