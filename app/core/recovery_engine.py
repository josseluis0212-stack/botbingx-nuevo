from app.logger import logger
from app.database.crud import TradeStateRepository
from app.exchange.bingx_client import AsyncBingXClient
from app.database.models import TradeState

class RecoveryEngine:
    """
    Se ejecuta al iniciar el bot. 
    1. Consulta Exchange.
    2. Consulta BD.
    3. Reconstruye el estado y retoma gestión.
    """

    def __init__(self, client: AsyncBingXClient):
        self.client = client
        self.repo = TradeStateRepository()

    async def recover_state(self) -> dict:
        """
        Devuelve un diccionario {symbol: TradeState} con las operaciones activas reales.
        """
        logger.info("=== INICIANDO RECOVERY ENGINE ===")
        logger.info("🧠 [MEMORIA BORRADA] Se ha reseteado el estado del bot o reiniciado el servidor.")
        reconstructed_state = {}

        # 1. Consultar BD
        db_trades = await self.repo.get_all_active_trades()
        db_map = {t.symbol: t for t in db_trades}
        
        # 2. Consultar Exchange (Posiciones Reales)
        try:
            real_positions = await self.client.get_positions()
        except Exception as e:
            logger.error(f"[RECOVERY] Error crítico consultando posiciones en exchange: {e}")
            # Fallback: confiar en BD si falla la API
            for t in db_trades:
                reconstructed_state[t.symbol] = t
            return reconstructed_state

        active_symbols_on_exchange = set()
        
        for pos in real_positions:
            amt = float(pos.get("positionAmt", 0))
            if abs(amt) > 0:
                symbol = pos.get("symbol")
                side = "LONG" if pos.get("positionSide") == "LONG" else "SHORT"
                active_symbols_on_exchange.add(symbol)
                
                # Existe en el exchange, ¿existe en la BD?
                if symbol in db_map:
                    trade = db_map[symbol]
                    # Actualizar tamaño restante real
                    trade.remaining_size = abs(amt)
                    reconstructed_state[symbol] = trade
                    logger.info(f"[RECOVERY] Reconstruida operación {side} en {symbol} desde BD. Tamaño real: {trade.remaining_size}")
                else:
                    logger.warning(f"🤝 [ADOPCIÓN] Operación huérfana detectada en exchange: {symbol} {side} amt={amt}. Iniciando protocolo de rescate...")
                    trade = await self._adopt_orphan(pos)
                    reconstructed_state[symbol] = trade

        # 3. Limpiar BD de operaciones que ya no existen en el exchange
        for symbol, trade in db_map.items():
            if symbol not in active_symbols_on_exchange:
                logger.info(f"[RECOVERY] La operación {symbol} existe en BD pero NO en el exchange. Marcando como cerrada.")
                await self.repo.mark_position_closed(symbol)

        logger.info(f"=== RECOVERY ENGINE FINALIZADO. {len(reconstructed_state)} posiciones recuperadas. ===")
        return reconstructed_state

    async def _adopt_orphan(self, pos: dict) -> TradeState:
        symbol = pos.get("symbol")
        side = "LONG" if pos.get("positionSide") == "LONG" else "SHORT"
        size = abs(float(pos.get("positionAmt", 0)))
        entry_price = float(pos.get("avgPrice", 0))
        if entry_price == 0:
            # Fallback if avgPrice is missing
            ticker = await self.client.get_ticker(symbol)
            entry_price = float(ticker.get("lastPrice", 0))

        logger.info(f"[ORPHAN ADOPTER] Evaluando adopción de {symbol} {side} a {entry_price}")
        
        # Calcular ATR para Stop Loss
        klines = await self.client.get_klines(symbol, "15m", limit=20)
        atr = entry_price * 0.01 # Default fallback 1%
        if klines and len(klines) > 14:
            from app.utils.indicators import calculate_atr
            highs = [float(k["high"]) for k in klines]
            lows = [float(k["low"]) for k in klines]
            closes = [float(k["close"]) for k in klines]
            atr_list = calculate_atr(highs, lows, closes, period=14)
            if len(atr_list) > 0:
                atr = atr_list[-1]
            
        # Calcular SL (2.5 ATR por defecto de protección)
        sl_price = entry_price - (atr * 2.5) if side == "LONG" else entry_price + (atr * 2.5)
        
        from app.exchange.order_executor import OrderExecutionEngine
        from app.risk.risk_manager import RiskManager
        
        executor = OrderExecutionEngine(self.client)
        
        # Calcular SL y TP usando la lógica de SMC_PRO (30/30/40) para huérfanas
        levels = RiskManager.calculate_levels(entry_price, atr, side, "SMC_PRO")
        dist = RiskManager.calculate_distribution(size, "SMC_PRO")
        
        # --- LÓGICA DINÁMICA DE ADOPCIÓN ---
        ticker = await self.client.get_ticker(symbol)
        current_price = float(ticker.get("lastPrice", entry_price))
        is_long = (side == "LONG")
        
        # Evaluar en qué etapa está:
        tp1 = levels["tp1_price"]
        lock_trigger = levels["lock_trigger_price"]
        lock_sl = levels["lock_sl_price"]
        
        crossed_lock = (is_long and current_price >= lock_trigger) or (not is_long and current_price <= lock_trigger)
        crossed_tp1 = (is_long and current_price >= tp1) or (not is_long and current_price <= tp1)
        
        sl_price_formatted = levels["sl_price"]
        tp1_qty = dist["tp1_qty"]
        tp2_qty = dist["tp2_qty"]
        
        if crossed_tp1:
            logger.info(f"🤝 [ADOPCIÓN DINÁMICA] {symbol} va en ALTA GANANCIA (> TP1). Asegurando con SL en ganancia.")
            sl_price_formatted = lock_sl # Aseguramos ganancias
            tp1_qty = 0 # Asumimos que ya lo pasó
            
        elif crossed_lock:
            logger.info(f"🤝 [ADOPCIÓN DINÁMICA] {symbol} va en POCA GANANCIA (> Breakeven). Asegurando Colchón.")
            sl_price_formatted = lock_sl # Aseguramos colchón
            
        else:
            logger.info(f"🤝 [ADOPCIÓN DINÁMICA] {symbol} está en RANGO INICIAL o PÉRDIDA. Colocando SL estándar a 2.0 ATR.")
            
        sl_id = await executor.place_stop_loss(symbol, side, size, sl_price_formatted)
        
        if not sl_id:
            logger.error(f"❌ [ADOPCIÓN FALLIDA PARCIAL] No se pudo colocar SL para {symbol}. Razón: Falla en API de BingX. Se adoptará pero dependerá del trailing o cierre manual.")
            sl_id = ""
            
        # Colocar TP1 y TP2 si aplican
        if tp1_qty > 0:
            await executor.place_take_profit(symbol, side, tp1_qty, levels["tp1_price"])
        if tp2_qty > 0:
            await executor.place_take_profit(symbol, side, tp2_qty, levels["tp2_price"])

        # Guardar en BD con estrategia "ADOPTED"
        import uuid
        trade = TradeState(
            trade_id=str(uuid.uuid4()), symbol=symbol, side=side, entry_price=entry_price,
            position_size=size, atr=atr, stop_loss=sl_price_formatted,
            tp1_price=levels["tp1_price"], tp2_price=levels["tp2_price"],
            profit_lock_price=levels["lock_trigger_price"],
            remaining_size=size, sl_order_id=sl_id,
            strategy="ADOPTED"
        )
        await self.repo.save_trade(trade)
        logger.info(f"🤝 [ADOPCIÓN EXITOSA] Operación huérfana encontrada en {symbol}. Adoptada con éxito. SL asegurado en {sl_price_formatted}.")
        return trade

    async def sweep_orphans(self) -> tuple:
        """
        Silent sweep run periodically to catch limit orders that filled while the bot was offline/restarting
        and became untracked positions.
        Returns a tuple (ghosts_cleaned, adopted_trades).
        """
        ghosts_cleaned = []
        adopted_trades = []
        try:
            real_positions = await self.client.get_positions()
            active_symbols_on_exchange = {p.get("symbol") for p in real_positions if abs(float(p.get("positionAmt", 0))) > 0}
            db_trades = await self.repo.get_all_active_trades()
            db_map = {t.symbol for t in db_trades}
            
            for pos in real_positions:
                amt = float(pos.get("positionAmt", 0))
                if abs(amt) > 0:
                    symbol = pos.get("symbol")
                    if symbol not in db_map:
                        # Double-check to prevent race condition if a trade is currently opening
                        import asyncio
                        await asyncio.sleep(15)
                        
                        db_trades_recheck = await self.repo.get_all_active_trades()
                        db_map_recheck = {t.symbol for t in db_trades_recheck}
                        
                        if symbol not in db_map_recheck:
                            side = "LONG" if pos.get("positionSide") == "LONG" else "SHORT"
                            logger.warning(f"[ORPHAN SWEEPER] Found untracked position: {symbol} {side} after 15s wait. Adoptando...")
                            trade = await self._adopt_orphan(pos)
                            adopted_trades.append(trade)
            
            # GHOST CLEANUP: Find trades in DB that are NO LONGER in the exchange (e.g. hit TP/SL silently)
            for symbol, trade in {t.symbol: t for t in db_trades}.items():
                if symbol not in active_symbols_on_exchange:
                    # Double-check
                    import asyncio
                    await asyncio.sleep(5)
                    real_positions_recheck = await self.client.get_positions()
                    active_symbols_recheck = {p.get("symbol") for p in real_positions_recheck if abs(float(p.get("positionAmt", 0))) > 0}
                    if symbol not in active_symbols_recheck:
                        logger.info(f"[GHOST SWEEPER] Trade {symbol} exists in DB but not on exchange. Marking as closed to sync dashboard.")
                        await self.repo.mark_position_closed(symbol)
                        ghosts_cleaned.append(symbol)
        except Exception as e:
            logger.error(f"[ORPHAN SWEEPER] Error: {e}")
        return ghosts_cleaned, adopted_trades
