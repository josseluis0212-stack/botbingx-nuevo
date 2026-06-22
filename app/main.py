import asyncio
import uvicorn
import os
import json
import time
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from app.core.engine import Engine
from app.logger import logger
from app.exchange.bingx_client import AsyncBingXClient
from app.config import Config
from app.constants import BOT_LOG_FILE, TRADES_FILE

engine = Engine()
bingx_client = AsyncBingXClient()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle manager."""
    logger.warning("=====================================================================")
    logger.warning("🚨 [SYSTEM ALERT] BOT RESTARTED / RECOVERED FROM RENDER SHUTDOWN")
    logger.warning("Si no fuiste tú quien reinició el bot, el servidor en la nube (Render)")
    logger.warning("mató el proceso y el bot acaba de revivir automáticamente.")
    logger.warning("=====================================================================")
    
    logger.info("Checking Hedge Mode...")
    await bingx_client.ensure_hedge_mode()

    logger.info("Starting QUANTUM BINGX Bot...")
    engine_task = asyncio.create_task(engine._safe_start())

    yield

    logger.info("Shutting down...")
    await engine.stop()
    engine_task.cancel()

app = FastAPI(
    title="QUANTUM BINGX Bot",
    description="SMC Strategy on BingX Demo",
    version="10.0.0",
    lifespan=lifespan
)

# Mount static files for Elite Terminal Dashboard
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    """Serve the Elite Terminal Dashboard."""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"error": "Dashboard UI not found. Did you create app/static/index.html?"})

# --- NEW APIS FOR ELITE TERMINAL ---

@app.post("/api/bot/start")
async def start_bot():
    if not engine.running:
        asyncio.create_task(engine._safe_start())
        return JSONResponse({"status": "started"})
    return JSONResponse({"status": "already_running"})

@app.post("/api/bot/stop")
async def stop_bot():
    if engine.running:
        await engine.stop()
        return JSONResponse({"status": "stopped"})
    return JSONResponse({"status": "already_stopped"})

@app.post("/api/bot/reset")
async def reset_bot():
    global _stats_cache, _stats_last_fetch
    await engine.reset_state()
    globals()["_stats_cache"] = None
    globals()["_stats_last_fetch"] = 0
    return JSONResponse({"status": "reset_completed"})

@app.post("/api/bot/reset_pnl_only")
async def reset_pnl_only():
    global _stats_cache, _stats_last_fetch
    import time
    pnl_file = os.path.join(Config.STORAGE_DIR, "pnl_start_time.txt")
    with open(pnl_file, "w") as f:
        f.write(str(int(time.time() * 1000)))
    globals()["_stats_cache"] = None
    globals()["_stats_last_fetch"] = 0
    return JSONResponse({"status": "pnl_reset_completed"})

@app.post("/api/bot/adjust_all_levels")
async def adjust_all_levels():
    try:
        updated = []
        for symbol, trade in list(engine.position_manager.trades.items()):
            if trade.position_closed:
                continue
            
            # Recalculate everything based on 4.0 ATR (R:R 1:2)
            sl_atr = 2.0
            tp_final_atr = 4.0
            tp1_atr = round(tp_final_atr * 0.30, 2)   # 1.2
            lock_atr = round(tp_final_atr * 0.333, 2) # 1.33
            tp2_atr = round(tp_final_atr * 0.60, 2)   # 2.4
            
            if trade.side == "LONG":
                new_tp1 = trade.entry_price + (tp1_atr * trade.atr)
                new_tp2 = trade.entry_price + (tp2_atr * trade.atr)
                new_lock = trade.entry_price + (lock_atr * trade.atr)
            else:
                new_tp1 = trade.entry_price - (tp1_atr * trade.atr)
                new_tp2 = trade.entry_price - (tp2_atr * trade.atr)
                new_lock = trade.entry_price - (lock_atr * trade.atr)
                
            trade.tp1_price = new_tp1
            trade.tp2_price = new_tp2
            trade.profit_lock_price = new_lock
            
            # Recreate orders on BingX
            open_orders = await engine.position_manager.client.get_open_orders(symbol)
            if open_orders is not None:
                for order in open_orders:
                    if order.get("type") == "TAKE_PROFIT_MARKET":
                        await engine.position_manager.executor.cancel_order(symbol, order.get("orderId"))
            
            dist = engine.position_manager.risk.calculate_distribution(trade.position_size)
            if not trade.tp1_filled:
                await engine.position_manager.executor.place_take_profit(symbol, trade.side, dist["tp1_qty"], new_tp1)
            if not trade.tp2_filled:
                await engine.position_manager.executor.place_take_profit(symbol, trade.side, dist["tp2_qty"], new_tp2)
                
            await engine.position_manager.repo.save_trade(trade)
            updated.append(f"{symbol}: Levels adjusted to 4.0 ATR math")
            
        return JSONResponse({"status": "adjusted", "updated": updated})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

@app.get("/api/dashboard")
async def api_dashboard():
    """Returns live balance, open positions, and strategy config."""
    try:
        balance = await bingx_client.get_balance()
        positions = await bingx_client.get_positions()
    except Exception as e:
        logger.error(f"Error fetching dashboard data from BingX: {e}")
        balance = 0.0
        positions = []

    # Filter out closed positions (size == 0)
    active_positions = [p for p in positions if abs(float(p.get("positionAmt", 0))) > 0]

    # Enrich each position with internal trade state (BE/Trailing status)
    enriched_positions = []
    for pos in active_positions:
        sym = pos.get("symbol", "")
        trade_state = engine.trade_state.get(sym, {})
        enriched = dict(pos)
        enriched["breakeven_hit"]    = trade_state.get("breakeven_hit", False)
        enriched["trailing_active"]  = trade_state.get("trailing_active", False)
        enriched["sl_price"]         = trade_state.get("sl_price", None)
        enriched["tp_price"]         = trade_state.get("tp_price", None)
        enriched["tp1_hit"]          = trade_state.get("tp1_hit", False)
        enriched["score"]            = trade_state.get("score", None)
        enriched["strategy"]         = trade_state.get("strategy", "N/A")
        enriched_positions.append(enriched)

    return JSONResponse({
        "status": "online",
        "balance": balance,
        "positions": enriched_positions,
        "config": {
            "leverage": Config.LEVERAGE,
            "max_trades": Config.MAX_OPEN_TRADES,
            "risk_per_trade": Config.POSITION_MARGIN
        }
    })

@app.get("/api/stats")
async def api_stats():
    """Calculates global performance from trades.json."""
    stats = {
        "pnl_today": 0.0, "win_today": 0, "loss_today": 0,
        "pnl_week": 0.0, "win_week": 0, "loss_week": 0,
        "pnl_month": 0.0, "win_month": 0, "loss_month": 0,
        "pnl_total": 0.0, "total_trades": 0,
        "win_rate": 0.0, "profit_factor": 0.0,
        "mean_win": 0.0, "mean_loss": 0.0,
        "recent_trades": []
    }

    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, "r") as f:
                trades = json.load(f)
            
            # If trades is a dict, get values
            if isinstance(trades, dict):
                trade_list = list(trades.values())
            else:
                trade_list = trades
                
            if trade_list:
                wins = 0
                losses = 0
                gross_profit = 0.0
                gross_loss = 0.0

                for t in trade_list:
                    pnl = float(t.get("pnl", 0.0) or 0.0)
                    stats["total_trades"] += 1

                    if pnl > 0:
                        wins += 1
                        gross_profit += pnl
                    elif pnl < 0:
                        losses += 1
                        gross_loss += abs(pnl)

                stats["win_rate"] = (wins / stats["total_trades"] * 100) if stats["total_trades"] > 0 else 0.0
                stats["profit_factor"] = (gross_profit / gross_loss) if gross_loss > 0 else (99.9 if gross_profit > 0 else 0.0)
                stats["mean_win"] = (gross_profit / wins) if wins > 0 else 0.0
                stats["mean_loss"] = (gross_loss / losses) if losses > 0 else 0.0

                # Sort by latest if possible, and return top 5
                stats["recent_trades"] = trade_list[-5:]
        except Exception as e:
            logger.error(f"Error calculating stats from trades.json: {e}")

    # We cache this heavy operation for 60 seconds
    global _stats_cache, _stats_last_fetch
    if "time" in globals() and time.time() - globals().get("_stats_last_fetch", 0) < 60:
        if globals().get("_stats_cache"):
            return JSONResponse(globals()["_stats_cache"])

    try:
        real_trades = []
        
        # Fetch Realized PNL and Fees separately to bypass the 1000 general limit
        # This extends the bot's memory back multiple weeks instead of 48 hours
        income_data = []
        try:
            pnl_req = await bingx_client._request("GET", "/openApi/swap/v2/user/income", params={"limit": 1000, "incomeType": "REALIZED_PNL"}, signed=True)
            if pnl_req and pnl_req.get("data"): income_data.extend(pnl_req["data"])
            
            fee_req = await bingx_client._request("GET", "/openApi/swap/v2/user/income", params={"limit": 1000, "incomeType": "TRADING_FEE"}, signed=True)
            if fee_req and fee_req.get("data"): income_data.extend(fee_req["data"])
        except Exception as api_e:
            logger.error(f"Error fetching extended income: {api_e}")
            # Fallback to standard
            income_data = await bingx_client.get_income(limit=1000)
        
        # Load PNL_START_TIME from storage/pnl_start_time.txt if exists
        pnl_start_time = getattr(Config, "PNL_START_TIME", 0)
        pnl_start_time_file = os.path.join(Config.STORAGE_DIR, "pnl_start_time.txt")
        if os.path.exists(pnl_start_time_file):
            try:
                with open(pnl_start_time_file, "r") as f:
                    pnl_start_time = int(f.read().strip())
            except Exception as e:
                logger.error(f"Error loading pnl_start_time.txt: {e}")

        now_ms = int(time.time() * 1000)
        
        # Calculate last 11:00 PM UTC-5 (which is 04:00 UTC)
        # Epoch 0 is 00:00 UTC. We get the start of today in UTC, add 4 hours.
        current_day_utc_start = (now_ms // 86400000) * 86400000
        reset_ms = current_day_utc_start + (4 * 3600 * 1000)
        if now_ms < reset_ms:
            reset_ms -= 86400000  # Reset was yesterday
            
        p_today = 0.0
        w_today = 0
        l_today = 0
        
        # Initialize vars for removed stats (to not break the return dict)
        p_week, p_month, p_total = 0.0, 0.0, 0.0
        w_week, w_month, l_week, l_month = 0, 0, 0, 0

        if income_data:
            for item in income_data:
                ts = int(item.get("time", 0))
                if ts < pnl_start_time:
                    continue  # Ignore old data before reset
                    
                if str(item.get("incomeType")) in ["2", "4", "REALIZED_PNL", "TRADING_FEE", "FUNDING_FEE"]:
                    amt = float(item.get("income", 0.0))
                    
                    p_total += amt
                    if ts >= reset_ms: 
                        p_today += amt
                        if str(item.get("incomeType")) in ["2", "REALIZED_PNL"]:
                            if amt > 0: w_today += 1
                            elif amt < 0: l_today += 1

            # Build history from REALIZED_PNL only
        for item in income_data:
            ts = int(item.get("time", 0))
            if ts < pnl_start_time:
                continue  # Ignore old trades in history
                
            if str(item.get("incomeType")) in ["2", "REALIZED_PNL"]:
                amt = float(item.get("income", 0.0))
                sym = item.get("symbol", "")
                info = item.get("info", "")
                ts = int(item.get("time", 0))
                side = "LONG" if "Sell" in info else ("SHORT" if "Buy" in info else "TRADE")
                
                # Try to enrich with local trade data
                local_strat = "UNKNOWN"
                local_reason = info
                local_be = False
                local_trail = False
                if 'trade_list' in locals() and trade_list:
                    for lt in trade_list:
                        if lt.get("symbol") == sym:
                            lt_time = lt.get("close_timestamp", 0) * 1000
                            # Allow up to 3 minutes delta
                            if abs(ts - lt_time) < 180000:
                                local_strat = lt.get("strategy", "UNKNOWN")
                                local_reason = lt.get("close_reason", info)
                                local_be = lt.get("breakeven_hit", False)
                                local_trail = lt.get("trailing_active", False)
                                break
                
                real_trades.append({
                    "symbol": sym,
                    "side": side,
                    "pnl": amt,
                    "reason": local_reason,
                    "strategy": local_strat,
                    "breakeven_hit": local_be,
                    "trailing_active": local_trail,
                    "time": ts
                })

        
        # Calculate real stats from real_trades
        wins = sum(1 for t in real_trades if t["pnl"] > 0)
        losses = sum(1 for t in real_trades if t["pnl"] < 0)
        gross_profit = sum(t["pnl"] for t in real_trades if t["pnl"] > 0)
        gross_loss = sum(abs(t["pnl"]) for t in real_trades if t["pnl"] < 0)
        total_trades = wins + losses

        stats["win_rate"] = (wins / total_trades * 100) if total_trades > 0 else 0.0
        stats["profit_factor"] = (gross_profit / gross_loss) if gross_loss > 0 else (99.9 if gross_profit > 0 else 0.0)
        stats["mean_win"] = (gross_profit / wins) if wins > 0 else 0.0
        stats["mean_loss"] = (gross_loss / losses) if losses > 0 else 0.0
        stats["total_trades"] = total_trades

        # Sort trades by time desc and take top 10
        real_trades.sort(key=lambda x: x["time"], reverse=True)
        stats["recent_trades"] = real_trades[:10]

        # Calculate strategy performance stats
        strat_stats = {}
        for t in real_trades:
            s_name = t.get("strategy", "UNKNOWN")
            if s_name not in strat_stats:
                strat_stats[s_name] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
            strat_stats[s_name]["trades"] += 1
            strat_stats[s_name]["pnl"] = round(strat_stats[s_name]["pnl"] + t["pnl"], 4)
            if t["pnl"] > 0:
                strat_stats[s_name]["wins"] += 1
            elif t["pnl"] < 0:
                strat_stats[s_name]["losses"] += 1
                
        stats["strategy_performance"] = strat_stats


        if income_data:
            stats["pnl_today"] = round(p_today, 2)
            stats["pnl_week"] = round(p_week, 2)
            stats["pnl_month"] = round(p_month, 2)
            stats["pnl_total"] = round(p_total, 2)
            
            stats["win_today"] = w_today
            stats["loss_today"] = l_today
            stats["win_week"] = w_week
            stats["loss_week"] = l_week
            stats["win_month"] = w_month
            stats["loss_month"] = l_month
            
        globals()["_stats_cache"] = stats
        globals()["_stats_last_fetch"] = time.time()
        
    except Exception as e:
        logger.error(f"Error computing live PNL from exchange: {e}")

    return JSONResponse(stats)

@app.get("/api/logs")
async def api_logs():
    """Returns the last 100 lines of the system log."""
    logs = []
    if os.path.exists(BOT_LOG_FILE):
        try:
            with open(BOT_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                logs = [l.strip() for l in lines[-100:] if l.strip()]
        except Exception as e:
            logs = [f"[ERROR] Could not read logs: {e}"]
    return JSONResponse({"logs": logs})

# --- OLD ENDPOINTS FOR COMPATIBILITY ---
@app.get("/status")
async def get_status():
    return JSONResponse({"status": "running"})

@app.get("/ping")
async def ping():
    return {"pong": True}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)