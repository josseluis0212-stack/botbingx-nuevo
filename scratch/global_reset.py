import asyncio
import sys
import os
import json
import urllib.request
import urllib.error

# Adjust path to import from app
sys.path.append(".")

from app.exchange.bingx_client import AsyncBingXClient
from app.logger import logger
from app.constants import POSITIONS_FILE, TRADES_FILE, PNL_OFFSET_FILE

async def run_global_reset():
    logger.info("=== STARTING GLOBAL EMERGENCY RESET ===")
    
    # 1. Close all active positions and orders on BingX (Demo Account)
    client = AsyncBingXClient()
    logger.info("Connecting to BingX Futures to close positions...")
    
    try:
        positions = await client.get_positions()
        closed_count = 0
        if positions:
            for p in positions:
                amt = abs(float(p.get("positionAmt", 0)))
                if amt > 0:
                    sym = p.get("symbol")
                    side = p.get("positionSide")
                    logger.info(f"Closing active position on exchange: {sym} {side} (Size={amt})...")
                    
                    pos_side = "LONG" if side == "LONG" else "SHORT"
                    close_side = "SELL" if side == "LONG" else "BUY"
                    
                    # Cancel all open orders for symbol
                    await client.cancel_all_orders(sym)
                    
                    res = await client.place_order(
                        symbol=sym,
                        side=close_side,
                        position_side=pos_side,
                        order_type="MARKET",
                        quantity=amt,
                        reduce_only=False
                    )
                    if res.get("success"):
                        logger.info(f"Successfully closed {sym} {side} position via MARKET order.")
                        closed_count += 1
                    else:
                        logger.error(f"Failed to close position: {res.get('msg')}")
                    await asyncio.sleep(0.5)
        logger.info(f"Closed {closed_count} positions and cancelled orders on exchange.")
    except Exception as e:
        logger.error(f"Error during exchange close/reset: {e}")

    # 2. Capture PNL Offset to normalize the dashboard to exactly 0.00
    pnl_offset = {"pnl_today": 0.0, "pnl_week": 0.0, "pnl_month": 0.0, "pnl_total": 0.0}
    try:
        income_data = await client.get_income(limit=1000)
        if income_data:
            import time
            now_ms = int(time.time() * 1000)
            day_ms = 24 * 60 * 60 * 1000
            week_ms = 7 * day_ms
            month_ms = 30 * day_ms
            
            p_today = 0.0; p_week = 0.0; p_month = 0.0; p_total = 0.0
            for item in income_data:
                if str(item.get("incomeType")) in ["2", "4", "REALIZED_PNL", "TRADING_FEE", "FUNDING_FEE"]:
                    amt = float(item.get("income", 0.0))
                    ts = int(item.get("time", 0))
                    p_total += amt
                    if now_ms - ts <= day_ms: p_today += amt
                    if now_ms - ts <= week_ms: p_week += amt
                    if now_ms - ts <= month_ms: p_month += amt
            pnl_offset = {"pnl_today": p_today, "pnl_week": p_week, "pnl_month": p_month, "pnl_total": p_total}
            logger.info(f"Calculated income offset to normalize dashboard to zero: {pnl_offset}")
    except Exception as e:
        logger.error(f"Error calculating PNL offset: {e}")

    # 3. Wipe local JSON files
    logger.info("Wiping local state files...")
    try:
        # Save empty state and clear logs
        with open(POSITIONS_FILE, "w") as f:
            json.dump({}, f)
        with open(TRADES_FILE, "w") as f:
            json.dump([], f)
        with open(PNL_OFFSET_FILE, "w") as f:
            json.dump(pnl_offset, f)
        
        import time
        pnl_start_time_file = os.path.join(os.path.dirname(POSITIONS_FILE), "pnl_start_time.txt")
        with open(pnl_start_time_file, "w") as f:
            f.write(str(int(time.time() * 1000)))
            
        logger.info("Local storage successfully cleared and normalized.")
    except Exception as e:
        logger.error(f"Error clearing local storage: {e}")

    # 4. Trigger reset and restart on Hugging Face Space Space API
    hf_url = "https://luisalbertor-botbingx.hf.space"
    logger.info(f"Sending reset trigger to HF Space Space: {hf_url}...")
    
    # Send /api/bot/reset
    try:
        req = urllib.request.Request(
            f"{hf_url}/api/bot/reset", 
            data=b"",  # POST request
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read().decode('utf-8')
            logger.info(f"HF Space Reset API Response: {res_body}")
    except urllib.error.URLError as e:
        logger.warning(f"Could not connect to HF Space Reset API: {e}")
    except Exception as e:
        logger.error(f"Error resetting HF Space: {e}")

    # Send /api/bot/start to resume engine execution
    try:
        req = urllib.request.Request(
            f"{hf_url}/api/bot/start", 
            data=b"",  # POST request
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read().decode('utf-8')
            logger.info(f"HF Space Start API Response: {res_body}")
    except urllib.error.URLError as e:
        logger.warning(f"Could not connect to HF Space Start API: {e}")
    except Exception as e:
        logger.error(f"Error starting HF Space engine: {e}")

    logger.info("=== GLOBAL EMERGENCY RESET COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    asyncio.run(run_global_reset())
