from app.exchange.bingx_client import AsyncBingXClient
from app.utils.indicators import calculate_ema, calculate_atr, calculate_adx, calculate_rsi, calculate_sma
from app.logger import logger
from app.config import Config

def detect_fvgs(candles: list, vol_sma: list) -> list:
    """Finds unmitigated FVGs with volume confirmation."""
    fvgs = []
    for i in range(2, len(candles) - 1): # Ignore very last forming candle
        c1, c2, c3 = candles[i-2], candles[i-1], candles[i]
        
        # Volume displacement confirmation
        has_volume = c2.get("volume", 0) > vol_sma[i-1]
        
        if has_volume:
            # Bullish FVG
            if c3["low"] > c1["high"]:
                fvgs.append({"type": "LONG", "top": c3["low"], "bottom": c1["high"], "index": i})
            # Bearish FVG
            elif c3["high"] < c1["low"]:
                fvgs.append({"type": "SHORT", "top": c1["low"], "bottom": c3["high"], "index": i})
    return fvgs

def detect_orderblocks(candles: list, vol_sma: list, atr: float = 0.0) -> list:
    """Finds valid Orderblocks with strong displacement."""
    obs = []
    for i in range(1, len(candles) - 2):
        c_prev, c_curr, c_next = candles[i-1], candles[i], candles[i+1]
        
        # Dynamic impulse threshold based on 1.5x ATR (Adapts to volatility)
        impulse_threshold = (atr / c_curr["close"]) * 1.5 if atr and c_curr["close"] > 0 else 0.005 
        
        has_volume = c_next.get("volume", 0) > vol_sma[i+1]
        
        if has_volume:
            # Bullish OB (Last bearish candle before bullish impulse)
            if c_curr["close"] < c_curr["open"]:
                move = (c_next["close"] - c_next["open"]) / c_next["open"]
                if move > impulse_threshold:
                    obs.append({"type": "LONG", "top": c_curr["high"], "bottom": c_curr["low"], "index": i})
                    
            # Bearish OB (Last bullish candle before bearish impulse)
            elif c_curr["close"] > c_curr["open"]:
                move = (c_next["open"] - c_next["close"]) / c_next["open"]
                if move > impulse_threshold:
                    obs.append({"type": "SHORT", "top": c_curr["high"], "bottom": c_curr["low"], "index": i})
    return obs

async def analyze(client: AsyncBingXClient, symbol: str) -> dict:
    """
    QUANTUM SMC 6x MULTI-STRATEGY ENGINE (SUPER HUNTER EDITION)
    """
    klines_15m = await client.get_klines(symbol, Config.TIMEFRAME, 150)
    klines_1h = await client.get_klines(symbol, "1h", 150)
    klines_1d = await client.get_klines(symbol, "1d", 10)
    
    if not klines_15m or len(klines_15m) < 50 or not klines_1h or len(klines_1h) < 101 or not klines_1d or len(klines_1d) < 2:
        return {"signal": "NONE"}
        
    klines_15m = klines_15m[:-1]
    klines_1h = klines_1h[:-1]
    
    closes_15m = [c["close"] for c in klines_15m]
    highs_15m = [c["high"] for c in klines_15m]
    lows_15m = [c["low"] for c in klines_15m]
    volumes_15m = [c.get("volume", 0) for c in klines_15m]
    closes_1h = [c["close"] for c in klines_1h]
    
    # Advanced Indicators
    ema100_1h = calculate_ema(closes_1h, 100)[-1]
    ema200_15m = calculate_ema(closes_15m, 200)[-1]
    atr = calculate_atr(highs_15m, lows_15m, closes_15m, 14)[-1]
    
    adx_list = calculate_adx(highs_15m, lows_15m, closes_15m, 14)
    adx_val = adx_list[-1] if adx_list else 0
    
    rsi_list = calculate_rsi(closes_15m, 14)
    rsi_val = rsi_list[-1] if rsi_list else 50
    
    vol_sma_15m = calculate_sma(volumes_15m, 20)
    
    current_price = klines_15m[-1]["close"]
    is_uptrend = current_price > ema100_1h
    is_downtrend = current_price < ema100_1h
    
    # We will collect valid setups here
    setups = []
    
    recent_20 = klines_15m[-20:]
    past_pool = klines_15m[-40:-20]
    last_closed = recent_20[-1]
    vol_sma_20 = vol_sma_15m[-20:]
    
    # ----------------------------------------------------
    # SETUP 1: AMD (Sweep + BOS) - Requires ADX Momentum
    # ----------------------------------------------------
    if adx_val > 20 and past_pool:
        if is_uptrend: # STRICT TREND
            swing_low = min([k["low"] for k in past_pool])
            sweep_candle = min(recent_20[:-1], key=lambda x: x["low"])
            if sweep_candle["low"] < swing_low:
                if last_closed["close"] > sweep_candle["high"] and last_closed["close"] > last_closed["open"]:
                    setups.append({
                        "signal": "LONG", "strategy": "SMC_AMD_BOS",
                        "entry": sweep_candle["high"], "sl": sweep_candle["low"] - (0.2 * atr)
                    })
        elif is_downtrend: # STRICT TREND
            swing_high = max([k["high"] for k in past_pool])
            sweep_candle = max(recent_20[:-1], key=lambda x: x["high"])
            if sweep_candle["high"] > swing_high:
                if last_closed["close"] < sweep_candle["low"] and last_closed["close"] < last_closed["open"]:
                    setups.append({
                        "signal": "SHORT", "strategy": "SMC_AMD_BOS",
                        "entry": sweep_candle["low"], "sl": sweep_candle["high"] + (0.2 * atr)
                    })

    # ----------------------------------------------------
    # SETUP 2 & 3: FVG / OB Mitigation (Volume Confirmed)
    # ----------------------------------------------------
    fvgs = detect_fvgs(recent_20, vol_sma_20)
    obs = detect_orderblocks(recent_20, vol_sma_20, atr)
    
    for fvg in fvgs:
        if is_uptrend and fvg["type"] == "LONG":
            if last_closed["low"] <= fvg["top"] and last_closed["close"] > fvg["bottom"]:
                if rsi_val < 50: # Confirmation: RSI exhaustion (not overbought)
                    setups.append({
                        "signal": "LONG", "strategy": "SMC_FVG_TAP",
                        "entry": current_price, "sl": fvg["bottom"] - (0.2 * atr)
                    })
        elif is_downtrend and fvg["type"] == "SHORT":
            if last_closed["high"] >= fvg["bottom"] and last_closed["close"] < fvg["top"]:
                if rsi_val > 50: # Confirmation: RSI exhaustion (not oversold)
                    setups.append({
                        "signal": "SHORT", "strategy": "SMC_FVG_TAP",
                        "entry": current_price, "sl": fvg["top"] + (0.2 * atr)
                    })
    for ob in obs:
        if is_uptrend and ob["type"] == "LONG":
            if last_closed["low"] <= ob["top"] and last_closed["close"] > ob["top"]:
                # RSI Divergence or Pullback Confirmation
                if rsi_val < 45 or last_closed["low"] < ema200_15m: 
                    setups.append({
                        "signal": "LONG", "strategy": "SMC_OB_TAP",
                        "entry": current_price, "sl": ob["bottom"] - (0.2 * atr)
                    })
        elif is_downtrend and ob["type"] == "SHORT":
            if last_closed["high"] >= ob["bottom"] and last_closed["close"] < ob["bottom"]:
                if rsi_val > 55 or last_closed["high"] > ema200_15m:
                    setups.append({
                        "signal": "SHORT", "strategy": "SMC_OB_TAP",
                        "entry": current_price, "sl": ob["top"] + (0.2 * atr)
                    })

    # ----------------------------------------------------
    # SETUP 4: PDH / PDL Sweep (RSI Exhaustion Confirmed)
    # ----------------------------------------------------
    prev_day = klines_1d[-2]
    pdh, pdl = prev_day["high"], prev_day["low"]
    
    # PDL Sweep (Reversal Long)
    if last_closed["low"] < pdl and last_closed["close"] > pdl and last_closed["close"] > last_closed["open"]:
        if rsi_val < 35: # Only if oversold
            setups.append({
                "signal": "LONG", "strategy": "SMC_PDL_SWEEP",
                "entry": current_price, "sl": last_closed["low"] - (0.2 * atr)
            })
            
    # PDH Sweep (Reversal Short)
    elif last_closed["high"] > pdh and last_closed["close"] < pdh and last_closed["close"] < last_closed["open"]:
        if rsi_val > 65: # Only if overbought
            setups.append({
                "signal": "SHORT", "strategy": "SMC_PDH_SWEEP",
                "entry": current_price, "sl": last_closed["high"] + (0.2 * atr)
            })

    # ----------------------------------------------------
    # SELECTION LOGIC & PREDICTIVE SCORING
    # ----------------------------------------------------
    if setups:
        best_setup = None
        highest_score = -1
        
        for s in setups:
            # 1. Calculate projected Take Profit (1:2 Risk Reward)
            risk = abs(s["entry"] - s["sl"])
            if risk == 0: continue
            
            if s["signal"] == "LONG":
                projected_tp = s["entry"] + (risk * 2.0)
            else:
                projected_tp = s["entry"] - (risk * 2.0)
                
            score = 0
            
            # 0. Dynamic required score based on strategy nature
            if s["strategy"] == "SMC_AMD_BOS":
                required_score = 65
            elif s["strategy"] in ["SMC_FVG_TAP", "SMC_OB_TAP"]:
                required_score = 60
            elif s["strategy"] in ["SMC_PDL_SWEEP", "SMC_PDH_SWEEP"]:
                required_score = 50
            else:
                required_score = 70
            
            # 2. Macro Trend Alignment (+20) - Only for continuation strategies
            if s["strategy"] not in ["SMC_PDL_SWEEP", "SMC_PDH_SWEEP"]:
                if s["signal"] == "LONG" and is_uptrend: score += 20
                if s["signal"] == "SHORT" and is_downtrend: score += 20
            
            # 3. Momentum Confirmation (+20)
            if adx_val > 25: score += 20
            elif adx_val > 20: score += 10
            
            # 4. Obstacle Detection (Path Clearance to TP2) (+30)
            path_clear = True
            if s["signal"] == "LONG":
                # Is there a major resistance below our TP?
                if s["entry"] < ema100_1h < projected_tp: path_clear = False
                if s["entry"] < ema200_15m < projected_tp: path_clear = False
                # Check recent swing highs blocking the way
                recent_high = max([k["high"] for k in klines_15m[-30:]])
                if s["entry"] < recent_high < projected_tp: path_clear = False
            else:
                # Is there a major support above our TP?
                if s["entry"] > ema100_1h > projected_tp: path_clear = False
                if s["entry"] > ema200_15m > projected_tp: path_clear = False
                # Check recent swing lows blocking the way
                recent_low = min([k["low"] for k in klines_15m[-30:]])
                if s["entry"] > recent_low > projected_tp: path_clear = False
                
            if path_clear: 
                score += 30
                logger.info(f"[PREDICTION] {s['strategy']} {s['signal']} has clear path to TP {projected_tp:.4f}.")
            else:
                logger.warning(f"[PREDICTION] {s['strategy']} {s['signal']} path blocked! TP {projected_tp:.4f} is behind a wall.")
            
            # 5. Volatility & RSI Exhaustion Advantage (+30)
            if s["signal"] == "LONG" and rsi_val < 40: score += 30
            elif s["signal"] == "SHORT" and rsi_val > 60: score += 30
            elif s["strategy"] in ["SMC_FVG_TAP", "SMC_OB_TAP"]: score += 20

            logger.info(f"[SCORE] {s['strategy']} {s['signal']} scored {score}/100")
            
            # 6. Filter and Pick Best
            if score >= required_score and score > highest_score:
                highest_score = score
                best_setup = s
                
        if best_setup:
            logger.info(f"[FIRE] Selected {best_setup['strategy']} {best_setup['signal']} with score {highest_score}/100. Punteria Maxima!")
            return {
                "signal": best_setup["signal"],
                "entry_price": best_setup["entry"],
                "sl_price": best_setup["sl"],
                "atr": atr,
                "strategy": best_setup["strategy"],
                "is_limit": False if best_setup["strategy"] != "SMC_AMD_BOS" else True,
                "score": highest_score
            }

    return {"signal": "NONE"}
