import asyncio
import time
from app.logger import logger
from app.exchange.bingx_client import AsyncBingXClient
from app.notifications.telegram import notifier
from app.state_manager import StateManager
from app.constants import RUNTIME_STATE_FILE

async def send_batch_report():
    """
    Called every 10 closed trades.
    Fetches the actual PnL from BingX using get_income over the last 24h/48h.
    """
    logger.info("[REPORTS] Generating batch report for the last 10 trades...")
    
    try:
        client = AsyncBingXClient()
        incomes = await client.get_income(limit=500)
        
        # We will calculate metrics from the internal trades.json to get Win Rate
        from app.constants import TRADES_FILE
        trades = await StateManager.load(TRADES_FILE, default=[])
        
        last_10 = trades[-10:] if len(trades) >= 10 else trades
        if not last_10:
            return
            
        wins = 0
        losses = 0
        for t in last_10:
            pnl = float(t.get("pnl", 0.0))
            if pnl > 0: wins += 1
            else: losses += 1
            
        win_rate = (wins / len(last_10)) * 100 if len(last_10) > 0 else 0
        
        internal_gross_pnl = sum(float(t.get("pnl", 0.0)) for t in last_10)
        
        # Estimate commissions for last 10 trades (approx 0.10% total per trade)
        total_vol = sum(float(t.get("entry_price", 0)) * float(t.get("total_size", 0)) for t in last_10)
        est_fees = total_vol * 0.001
        
        net_pnl = internal_gross_pnl - est_fees
        
        text = (
            f"📊 <b>REPORTE DE RENDIMIENTO</b>\n"
            f"<i>(Últimas {len(last_10)} Operaciones)</i>\n"
            f"─────────────────\n"
            f"🏆 <b>Tasa de Acierto:</b> {win_rate:.1f}% ({wins}W / {losses}L)\n"
            f"💸 <b>Comisiones Est.:</b> -{est_fees:.2f} USDT\n"
            f"💵 <b>PNL Neto (10 trades):</b> <b>{net_pnl:.2f} USDT</b>\n"
            f"─────────────────\n"
            f"🤖 <i>SMC PRO V1 - BingX</i>"
        )
        
        await notifier.send_message(text)
        
        # Reset the counter
        state = await StateManager.load(RUNTIME_STATE_FILE, default={})
        state["trades_closed_since_report"] = 0
        await StateManager.save(RUNTIME_STATE_FILE, state)
        
    except Exception as e:
        logger.error(f"[REPORTS] Error generating batch report: {e}")
