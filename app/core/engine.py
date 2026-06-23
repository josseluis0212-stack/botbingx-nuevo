import asyncio
import time
from app.logger import logger
from app.config import Config
from app.exchange.bingx_client import AsyncBingXClient
from app.core.position_manager import PositionManager
from app.core.recovery_engine import RecoveryEngine
from app.strategy.smc_pro_v1 import analyze as evaluate_smc_pro
from app.strategy.supertrend_ema_mtf_pro import analyze as evaluate_supertrend_pro
from app.strategy.bustos_pullback import evaluate_bustos_pullback
from app.strategy.liquidity_sweep import evaluate_liquidity_sweep
from app.database.crud import init_db

class Engine:
    """
    Main Engine. Actúa como el Escáner del Mercado (MarketScanner) y
    delega toda la gestión del trade al PositionManager oficial.
    """
    def __init__(self):
        self.client = AsyncBingXClient()
        self.position_manager = PositionManager(self.client)
        self.recovery = RecoveryEngine(self.client)
        self.running = False
        self.tracked_symbols = []
        self.btc_blocked_until = 0.0

    @property
    def trade_state(self):
        # Expose trades dict for main.py compatibility (dashboard)
        # Convert TradeState models to dicts
        out = {}
        for sym, t in self.position_manager.trades.items():
            out[sym] = {
                "side": t.side,
                "strategy": getattr(t, "strategy", "SMC_PRO"),
                "entry_price": t.entry_price,
                "sl_price": t.stop_loss,
                "tp_price": t.tp2_price,
                "breakeven_hit": t.profit_lock_active,
                "trailing_active": t.trailing_active,
                "score": 100
            }
        return out

    async def start(self):
        self.running = True
        logger.info("=== STARTING QUANTUM ENGINE (OFFICIAL 30/30/40) ===")
        
        # 1. Init DB
        await init_db()
        
        # 2. Recovery
        recovered = await self.recovery.recover_state()
        self.position_manager.set_recovered_state(recovered)
        
        # 3. Start Position Manager
        await self.position_manager.start()

        # 4. Start periodic orphan sweeper
        asyncio.create_task(self._orphan_sweeper_task())

        # 5. Fetch Symbols
        try:
            symbols = await self.client.get_top_volume_symbols(25)
            if symbols:
                if "BTC-USDT" not in symbols: symbols.insert(0, "BTC-USDT")
                self.tracked_symbols = symbols[:25]
        except Exception as e:
            self.tracked_symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]

        # 5. Start Scanner
        asyncio.create_task(self._scanner_loop())

    async def _safe_start(self):
        try:
            await self.start()
        except Exception as e:
            logger.error(f"[ENGINE FATAL ERROR] Failed to start engine: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _orphan_sweeper_task(self):
        """Runs periodically to catch any limit orders that filled while the bot was disconnected."""
        while self.running:
            await asyncio.sleep(300) # Check every 5 minutes
            if self.running:
                ghosts = await self.recovery.sweep_orphans()
                for sym in ghosts:
                    if sym in self.position_manager.trades:
                        logger.info(f"[ENGINE] Sincronizando dashboard: Removiendo trade fantasma {sym} de memoria.")
                        del self.position_manager.trades[sym]

    async def stop(self):
        self.running = False
        await self.position_manager.stop()

    async def reset_state(self):
        """Force resets the engine and clears trades."""
        await self.stop()
        from app.database.crud import TradeStateRepository
        repo = TradeStateRepository()
        for sym in list(self.position_manager.trades.keys()):
            await repo.mark_position_closed(sym)
            
            # Close position on exchange immediately
            try:
                from app.exchange.order_executor import OrderExecutionEngine
                executor = OrderExecutionEngine(self.client)
                
                # We don't know the exact size here easily from exchange without a call, 
                # but we can fetch positions and close all
            except Exception as e:
                logger.error(f"Error during reset_state close for {sym}: {e}")
                
        self.position_manager.trades.clear()
        
        # Fetch and close ALL active positions on BingX to clear the dashboard
        try:
            positions = await self.client.get_positions()
            from app.exchange.order_executor import OrderExecutionEngine
            executor = OrderExecutionEngine(self.client)
            for pos in positions:
                amt = float(pos.get("positionAmt", 0))
                if abs(amt) > 0:
                    sym = pos.get("symbol")
                    side = "LONG" if amt > 0 else "SHORT"
                    await executor.close_position_market(sym, side, abs(amt))
                    await executor.cancel_all_orders(sym)
        except Exception as e:
            logger.error(f"Error closing all exchange positions on reset: {e}")
        
        # Guardar archivo pnl timestamp
        import os
        from app.constants import STORAGE_DIR
        try:
            with open(os.path.join(STORAGE_DIR, "pnl_start_time.txt"), "w") as f:
                f.write(str(int(time.time() * 1000)))
        except: pass
        
        await self.start()

    async def _scanner_loop(self):
        logger.info("[SCANNER] Market scanner active (60s interval).")
        while self.running:
            if not self.tracked_symbols:
                await asyncio.sleep(5)
                continue

            for symbol in self.tracked_symbols:
                if not self.running: break
                try:
                    await self._evaluate_symbol(symbol)
                except Exception as e:
                    logger.error(f"[SCANNER] Error evaluating {symbol}: {e}")
                await asyncio.sleep(0.5)

            await asyncio.sleep(60)

    async def _evaluate_symbol(self, symbol: str):
        # Prevent duplicate logic
        if symbol in self.position_manager.trades:
            return

        from app.database.crud import is_on_cooldown
        if await is_on_cooldown(symbol):
            return

        sweep_result = await evaluate_smc_pro(self.client, symbol)
        
        # Multi-Strategy Engine: Evaluate in sequence (waterfall)
        selected_signal = None
        strategy_name = "SMC_PRO"
        
        if sweep_result["signal"] != "NONE":
            selected_signal = sweep_result
            strategy_name = sweep_result.get("strategy", "SMC_PRO")
        else:
            sweep_st = await evaluate_supertrend_pro(self.client, symbol)
            if sweep_st["signal"] != "NONE":
                selected_signal = sweep_st
                strategy_name = sweep_st.get("strategy", "SUPERTREND_EMA_MTF_PRO")
            else:
                sweep_bustos = await evaluate_bustos_pullback(self.client, symbol)
                if sweep_bustos["signal"] != "NONE":
                    selected_signal = sweep_bustos
                    strategy_name = sweep_bustos.get("strategy", "BUSTOS_PULLBACK")
                else:
                    sweep_liquidity = await evaluate_liquidity_sweep(self.client, symbol)
                    if sweep_liquidity["signal"] != "NONE":
                        selected_signal = sweep_liquidity
                        strategy_name = sweep_liquidity.get("strategy", "LIQUIDITY_SWEEP")
                
        if not selected_signal:
            return

        # Trigger Trade
        signal = selected_signal["signal"]
        entry = selected_signal.get("entry_price")
        atr = selected_signal.get("atr", entry * 0.01) # Fallback to 1% atr if not passed
        
        # ----------------------------------------------------
        # PRICE ACTION FILTER (VULNERABILITY CHECK)
        # ----------------------------------------------------
        from app.risk.price_action import PriceActionFilter
        from app.risk.risk_manager import RiskManager
        
        rm = RiskManager()
        levels = RiskManager.calculate_levels(entry, atr, signal, strategy_name)
        math_sl = levels["sl_price"]
        
        try:
            klines = await self.client.get_klines(symbol, "15m", limit=50)
            if klines and len(klines) >= 40:
                highs   = [float(k["high"]) for k in klines]
                lows    = [float(k["low"]) for k in klines]
                volumes = [float(k.get("volume", 0)) for k in klines]
                
                # -- Price Action Vulnerability Check --
                # El filtro de Price Action aplica para estrategias de reversión/SMC, pero puede bloquear estrategias de momentum puro.
                is_supertrend = "SUPERTREND" in strategy_name or "ST" in strategy_name
                
                if is_supertrend:
                    logger.info(f"[FILTERS] {symbol} {signal} Bypassing Price Action y Volume filters para estrategia de momentum: {strategy_name}")
                else:
                    is_safe = PriceActionFilter.is_trade_safe(symbol, signal, entry, math_sl, highs, lows)
                    if not is_safe:
                        return # Reject: SL is structurally exposed
                
                # -- Volume Confirmation (per-strategy) --
                if not is_supertrend:
                    from app.risk.volume_filter import VolumeFilter
                    vol_ok = VolumeFilter.is_volume_valid(symbol, signal, strategy_name, klines, volumes)
                    if not vol_ok:
                        return # Reject: no institutional volume conviction

        except Exception as e:
            logger.error(f"[SCANNER] Error en filtros de Price Action/Volumen: {e}")
        # ----------------------------------------------------

        logger.info(f"[SCANNER] FIRE {strategy_name}! {symbol} {signal} @ {entry} (ATR: {atr:.8f})")
        
        asyncio.create_task(self.position_manager.open_trade(
            symbol=symbol,
            side=signal,
            atr=atr,
            price=entry,
            strategy_name=strategy_name
        ))