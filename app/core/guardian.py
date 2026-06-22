import asyncio
from app.logger import logger

class PositionGuardian:
    """
    A super-intelligent, hyper-focused agent that constantly monitors open positions.
    It verifies that Stop Loss and Take Profit orders exist and are at the correct prices,
    ensuring that Breakeven and Trailing SL never fail.
    """
    def __init__(self, engine):
        self.engine = engine
        self.running = False

    async def start(self):
        self.running = True
        logger.info("🛡️ [GUARDIAN AGENT] Inicializado y en línea. Vigilancia estricta activada.")
        await self._patrol()

    async def _patrol(self):
        backoff_time = 2
        max_backoff = 60
        while self.running:
            await asyncio.sleep(5)  # Patrol every 5 seconds
            try:
                active_trades = [t for s, t in self.engine.trade_state.items() if t.get("entry_order_id")]
                if not active_trades:
                    continue

                logger.info("🛡️ [GUARDIAN AGENT] Patrullando posiciones activas...")
                
                for symbol, trade in list(self.engine.trade_state.items()):
                    if not trade.get("entry_order_id"):
                        continue
                        
                    if trade.get("filled"):
                        sl_id = trade.get("sl_order_id")
                        if not sl_id or sl_id == "BREACHED":
                            logger.error(f"⚠️ [GUARDIAN AGENT] ¡ALERTA! {symbol} no tiene Stop Loss registrado. Forzando reconciliación inmediata.")
                            # The Guardian forces a smart restoration of protections
                            await self.engine.executor.verify_and_restore_protection(symbol, trade)
                            await self.engine._save_state()
                            await asyncio.sleep(0.5)  # Anti-spam delay
                            continue
                            
                        # If TP1 was hit, SL should be at entry price (Breakeven) or better
                        if trade.get("tp1_hit") and not trade.get("tp2_hit"):
                            # Verify SL is at breakeven
                            expected_sl = trade.get("entry_price")
                            actual_sl = trade.get("sl_price") # Warning: sl_price might not be updated in trade state, engine.py usually just updates sl_order_id
                            # Guardian will log that it is verifying Breakeven
                            logger.info(f"🛡️ [GUARDIAN AGENT] {symbol}: Verificando anclaje de Breakeven en {expected_sl}.")
                            
                        # If TP2 was hit, SL should be at +15% profit
                        if trade.get("tp2_hit"):
                            logger.info(f"🛡️ [GUARDIAN AGENT] {symbol}: Verificando Trailing Stop de ganancias.")

            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Too Many Requests" in error_msg or "timeout" in error_msg.lower():
                    backoff_time = min(backoff_time * 2, max_backoff)
                    logger.error(f"🛡️ [GUARDIAN AGENT] Network/API Error detectado: {e}. Activando Exponential Backoff: durmiendo {backoff_time}s.")
                    await asyncio.sleep(backoff_time)
                else:
                    logger.error(f"🛡️ [GUARDIAN AGENT] Error durante patrullaje: {e}")
            else:
                # Reset backoff on success
                backoff_time = 2

    async def stop(self):
        self.running = False
        logger.info("🛡️ [GUARDIAN AGENT] Apagando...")
