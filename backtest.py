import asyncio
from datetime import datetime
from app.exchange.bingx_client import AsyncBingXClient
from app.utils.indicators import calculate_ema, calculate_adx, calculate_atr
from app.strategy.supertrend_ema_mtf_pro import calculate_supertrend

async def backtest():
    client = AsyncBingXClient()
    symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
    print("=== FAST BACKTEST SUPERTREND EMA MTF PRO (Last 10 days) ===\\n")
    
    for symbol in symbols:
        klines_15m = await client.get_klines(symbol, "15m", limit=1000)
        klines_1h = await client.get_klines(symbol, "1h", limit=300)
        
        if not klines_15m or not klines_1h:
            continue
            
        closes_15m = [k["close"] for k in klines_15m]
        highs_15m = [k["high"] for k in klines_15m]
        lows_15m = [k["low"] for k in klines_15m]
        
        st_results = calculate_supertrend(highs_15m, lows_15m, closes_15m, 10, 3.0)
        dir_15m = [x["dir"] for x in st_results]
        adx_15m = calculate_adx(highs_15m, lows_15m, closes_15m, 14)
        atr_15m = calculate_atr(highs_15m, lows_15m, closes_15m, 10)
        ema200_15m = calculate_ema(closes_15m, 200)
        ema9_15m = calculate_ema(closes_15m, 9)
        ema21_15m = calculate_ema(closes_15m, 21)
        
        closes_1h = [k["close"] for k in klines_1h]
        ema200_1h = calculate_ema(closes_1h, 200)
        ema9_1h = calculate_ema(closes_1h, 9)
        ema21_1h = calculate_ema(closes_1h, 21)
        
        trades = []
        current_trade = None
        
        for i in range(250, len(klines_15m)):
            k = klines_15m[i]
            current_time = k["time"]
            
            idx_1h = -1
            for j in range(len(klines_1h)-1, -1, -1):
                if klines_1h[j]["time"] <= current_time:
                    idx_1h = j
                    break
            
            if idx_1h < 0: continue
            
            if current_trade:
                low = k["low"]
                high = k["high"]
                close = k["close"]
                
                side = current_trade["side"]
                sl = current_trade["sl"]
                entry = current_trade["entry"]
                
                ema21 = ema21_15m[i]
                atr = current_trade["atr"]
                
                if side == "LONG":
                    if high > current_trade["highest"]: current_trade["highest"] = high
                    if low <= sl:
                        current_trade["exit"] = sl
                        current_trade["pnl"] = (sl - entry) / entry
                        current_trade["exit_time"] = current_time
                        trades.append(current_trade)
                        current_trade = None
                        continue
                        
                    profit_distance = close - entry
                    target_roe = 0.15
                    price_change_for_roe = (target_roe / 10.0) * entry
                    if profit_distance >= (2.0 * atr):
                        lock_sl = entry + price_change_for_roe
                        if lock_sl > sl: sl = lock_sl; current_trade["sl"] = sl
                            
                    if profit_distance >= (2.5 * atr):
                        if ema21 > sl: sl = ema21; current_trade["sl"] = sl
                            
                else:
                    if low < current_trade["lowest"]: current_trade["lowest"] = low
                    if high >= sl:
                        current_trade["exit"] = sl
                        current_trade["pnl"] = (entry - sl) / entry
                        current_trade["exit_time"] = current_time
                        trades.append(current_trade)
                        current_trade = None
                        continue
                        
                    profit_distance = entry - close
                    target_roe = 0.15
                    price_change_for_roe = (target_roe / 10.0) * entry
                    if profit_distance >= (2.0 * atr):
                        lock_sl = entry - price_change_for_roe
                        if lock_sl < sl: sl = lock_sl; current_trade["sl"] = sl
                            
                    if profit_distance >= (2.5 * atr):
                        if ema21 < sl: sl = ema21; current_trade["sl"] = sl
                continue
                
            c_price = closes_15m[i]
            current_adx = adx_15m[i]
            current_atr = atr_15m[i]
            c_ema200 = ema200_15m[i]
            c_ema9 = ema9_15m[i]
            c_ema21 = ema21_15m[i]
            p_ema200 = ema200_15m[i-10]
            
            c_ema200_1h = ema200_1h[idx_1h]
            c_ema9_1h = ema9_1h[idx_1h]
            c_ema21_1h = ema21_1h[idx_1h]
            
            signal = "NONE"
            was_red = -1 in dir_15m[i-160:i]
            is_green = dir_15m[i] == 1
            if was_red and is_green and c_price > c_ema9:
                if current_adx >= 18:
                    if c_price > c_ema200 and (c_price - c_ema200) > (0.3 * current_atr):
                        if c_ema200 > p_ema200:
                            if c_ema9 > c_ema21:
                                if c_price > c_ema200_1h and c_ema9_1h > c_ema21_1h:
                                    signal = "LONG"
                                    
            was_green = 1 in dir_15m[i-160:i]
            is_red = dir_15m[i] == -1
            if was_green and is_red and c_price < c_ema9:
                if current_adx >= 18:
                    if c_price < c_ema200 and (c_ema200 - c_price) > (0.3 * current_atr):
                        if c_ema200 < p_ema200:
                            if c_ema9 < c_ema21:
                                if c_price < c_ema200_1h and c_ema9_1h < c_ema21_1h:
                                    signal = "SHORT"
                                    
            if signal != "NONE":
                sl_dist = 2.5 * current_atr
                sl = c_price - sl_dist if signal == "LONG" else c_price + sl_dist
                dt = datetime.fromtimestamp(current_time/1000.0)
                current_trade = {
                    "side": signal,
                    "entry": c_price,
                    "sl": sl,
                    "atr": current_atr,
                    "highest": c_price,
                    "lowest": c_price,
                    "entry_time": dt,
                    "pnl": 0
                }

        print(f"--- RESULTS {symbol} ---")
        if not trades and not current_trade:
            print("No trades executed. Very strict conditions.")
        
        wins = 0; losses = 0; total_pnl = 0
        for t in trades:
            win = t["pnl"] > 0
            if win: wins += 1
            else: losses += 1
            total_pnl += t["pnl"] * 10
            print(f"[{t['entry_time']}] {t['side']} at {t['entry']:.4f} -> Closed {t['exit']:.4f} | PNL: {t['pnl']*10*100:.2f}% (ROE)")
            
        if current_trade:
            print(f"[{current_trade['entry_time']}] {current_trade['side']} OPEN at {current_trade['entry']:.4f}")
            
        print(f"Wins: {wins} | Losses: {losses} | Net ROE: {total_pnl*100:.2f}%\\n")

if __name__ == "__main__":
    asyncio.run(backtest())
