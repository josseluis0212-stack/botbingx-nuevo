import asyncio
import time
from app.logger import logger
from app.exchange.bingx_client import AsyncBingXClient
from app.core.exchange_synchronizer import ExchangeSynchronizer
from app.exchange.order_executor import OrderExecutionEngine
from app.risk.risk_manager import RiskManager
from app.risk.trailing_manager import TrailingManager
from app.database.crud import TradeStateRepository
from app.database.models import TradeState
from app.notifications.telegram import notifier

class PositionManager:
    """
    Núcleo principal (Arquitectura Oficial 30/30/40).
    Mantiene el control de todas las posiciones mediante un Supervisor de Seguridad estricto.
    """
    def __init__(self, client: AsyncBingXClient):
        self.client = client
        self.sync = ExchangeSynchronizer(self.client)
        self.executor = OrderExecutionEngine(self.client)
        self.risk = RiskManager()
        self.trailing = TrailingManager()
        self.repo = TradeStateRepository()
        self.running = False
        self.trades = {} # Dict[symbol, TradeState]

        # Register callbacks to the Synchronizer
        self.sync.register_price_callback(self._on_mark_price)
        self.sync.register_fill_callback(self._on_order_fill)
        self._last_sl_retry = {} # symbol -> timestamp
        self._last_kline_check = {} # symbol -> timestamp

    async def start(self):
        self.running = True
        await self.sync.start()
        asyncio.create_task(self._supervisor_loop())
        logger.info("[POSITION MANAGER] Supervisor Engine and Synchronizer Started.")

    async def stop(self):
        self.running = False
        await self.sync.stop()

    def set_recovered_state(self, state: dict):
        """Loads state reconstructed by RecoveryEngine."""
        self.trades = state

    async def _supervisor_loop(self):
        """SUPERVISOR DE SEGURIDAD (CADA 5 SEGUNDOS)"""
        while self.running:
            await asyncio.sleep(5)
            try:
                await self._enforce_security_checks()
            except Exception as e:
                logger.error(f"[SUPERVISOR] Exception during check: {e}")

    async def _enforce_security_checks(self):
        """Verifica SL, TPs, Trailing y Sincronización."""
        for symbol, trade in list(self.trades.items()):
            if trade.position_closed:
                self.trades.pop(symbol, None)
                continue

            # Verify the position actually exists on BingX
            pos_data = await self.client.get_positions(symbol)
            actual_size = 0.0
            if pos_data:
                for p in pos_data:
                    if abs(float(p.get("positionAmt", 0))) > 0:
                        actual_size = abs(float(p.get("positionAmt", 0)))
            
            if actual_size == 0.0:
                logger.warning(f"[SUPERVISOR] {symbol} position is 0 on BingX but active locally. Closing locally.")
                trade.position_closed = True
                await self.repo.mark_position_closed(symbol)
                self.trades.pop(symbol, None)
                continue

            # --- 0. VISIÓN RETROACTIVA: Auditoría Histórica con K-lines (Cada 60s) ---
            now = time.time()
            last_kline = self._last_kline_check.get(symbol, 0)
            if now - last_kline > 60:
                try:
                    # Extraer velas históricas (última hora) para cubrir apagones
                    klines = await self.client.get_klines(symbol, interval="5m", limit=12)
                    if klines:
                        if trade.highest_price is None: trade.highest_price = trade.entry_price
                        if trade.lowest_price is None: trade.lowest_price = trade.entry_price
                        for k in klines:
                            h = k["high"]
                            l = k["low"]
                            if h > trade.highest_price: trade.highest_price = h
                            if l > 0 and l < trade.lowest_price: trade.lowest_price = l
                            
                        # Someter los extremos al Vigilante para forzar activación retroactiva
                        if trade.side == "LONG":
                            await self._on_mark_price(symbol, trade.lowest_price)
                            if not trade.position_closed:
                                await self._on_mark_price(symbol, trade.highest_price)
                        else:
                            await self._on_mark_price(symbol, trade.highest_price)
                            if not trade.position_closed:
                                await self._on_mark_price(symbol, trade.lowest_price)
                                
                        await self.repo.save_trade(trade)
                        
                    # Dynamic strategy exits
                    strategy_name = getattr(trade, "strategy", "SMC_PRO")
                    if strategy_name in ["SUPERTREND_EMA_MTF", "SUPERTREND_EMA_MTF_PRO"]:
                        if strategy_name == "SUPERTREND_EMA_MTF":
                            from app.strategy.supertrend_ema_mtf import check_exit
                        else:
                            from app.strategy.supertrend_ema_mtf_pro import check_exit
                        
                        klines_15m = await self.client.get_klines(symbol, interval="15m", limit=200)
                        
                        # Extraer la EMA21 en tiempo real para el Trailing Stop Dinámico
                        if klines_15m:
                            from app.utils.indicators import calculate_ema
                            closes_15m = [float(k["close"]) for k in klines_15m]
                            ema21s = calculate_ema(closes_15m, 21)
                            if len(ema21s) > 0:
                                trade.dynamic_ema21 = ema21s[-1]

                        if check_exit(trade, klines_15m=klines_15m):
                            logger.warning(f"[SUPERVISOR] {symbol} {strategy_name} Exit Condition Hit! Closing at market.")
                            await self.executor.close_position_market(symbol, trade.side, trade.remaining_size)
                            trade.position_closed = True
                            await self.repo.mark_position_closed(symbol)
                            self.trades.pop(symbol, None)
                            from app.notifications.telegram import notifier
                            asyncio.create_task(notifier.notify_close(symbol, trade.side, "Opposite Trend Exit (SuperTrend)"))
                            continue
                            
                        # Update EMA21 Trailing Stop if active
                        if trade.trailing_active:
                            from app.utils.indicators import calculate_ema
                            closes = [k["close"] for k in klines_15m]
                            ema21 = calculate_ema(closes, 21)[-1]
                            
                            new_sl = trade.stop_loss
                            if trade.side == "LONG" and ema21 > trade.stop_loss:
                                new_sl = ema21
                            elif trade.side == "SHORT" and ema21 < trade.stop_loss:
                                new_sl = ema21
                                
                            if new_sl != trade.stop_loss:
                                logger.info(f"[TRAILING] {symbol} {strategy_name} updating SL to EMA21: {new_sl:.6f}")
                                trade.stop_loss = new_sl
                                await self.executor.cancel_order(symbol, trade.sl_order_id)
                                trade.sl_order_id = await self.executor.place_stop_loss(symbol, trade.side, trade.remaining_size, trade.stop_loss)
                                await self.repo.save_trade(trade)
                    
                    self._last_kline_check[symbol] = now
                except Exception as e:
                    logger.error(f"[SUPERVISOR] Error en Visión Retroactiva para {symbol}: {e}")

            if trade.position_closed:
                continue

            open_orders = await self.client.get_open_orders(symbol)
            if open_orders is None: continue # Network issue

            has_sl = False
            has_tp = False

            for o in open_orders:
                if o.get("type") == "STOP_MARKET": has_sl = True
                elif o.get("type") == "TAKE_PROFIT_MARKET": has_tp = True

            # SI FALTA UN STOP LOSS: RECREARLO
            if not has_sl:
                now = time.time()
                last_retry = self._last_sl_retry.get(symbol, 0)
                if now - last_retry > 30: # Reducido a 30s para mayor inteligencia
                    logger.warning(f"[SUPERVISOR] {symbol} missing SL! Recreating...")
                    new_id = await self.executor.place_stop_loss(symbol, trade.side, trade.remaining_size, trade.stop_loss)
                    if new_id:
                        trade.sl_order_id = new_id
                        await self.repo.save_trade(trade)
                        self._last_sl_retry[symbol] = 0 # reset failures
                    else:
                        # Fail counter logic
                        fails = self._last_sl_retry.get(f"{symbol}_fails", 0) + 1
                        self._last_sl_retry[f"{symbol}_fails"] = fails
                        if fails >= 3:
                            logger.error(f"[EMERGENCY] {symbol} is UNPROTECTED after 3 SL failures! CLOSING AT MARKET.")
                            await self.executor.close_position_market(symbol, trade.side, actual_size)
                            trade.position_closed = True
                            await self.repo.mark_position_closed(symbol)
                            self.trades.pop(symbol, None)
                            continue
                    self._last_sl_retry[symbol] = now

            # SI EXISTE INCONSISTENCIA: CORREGIRLA (Restaurar TPs si no ha tocado trailing)
            strategy_name = getattr(trade, "strategy", "SMC_PRO")
            if "SUPERTREND" not in strategy_name and "AMD" not in strategy_name and "BUSTOS" not in strategy_name:
                if not trade.trailing_active and not has_tp:
                    dist = self.risk.calculate_distribution(trade.position_size, strategy_name)
                    # Need to restore either TP1 or TP2 depending on state
                    if not trade.tp1_filled and dist["tp1_qty"] > 0:
                        target_tp_price = trade.tp1_price
                        qty = dist["tp1_qty"]
                    elif not trade.tp2_filled and dist["tp2_qty"] > 0:
                        target_tp_price = trade.tp2_price
                        qty = dist["tp2_qty"]
                    else:
                        target_tp_price = 0
                        qty = 0
                        
                    if target_tp_price > 0:
                        logger.warning(f"[SUPERVISOR] {symbol} missing TP! Recreating at {target_tp_price}...")
                        await self.executor.place_take_profit(symbol, trade.side, qty, target_tp_price)

    async def _on_mark_price(self, symbol: str, price: float):
        """Procesa ticks de precio en tiempo real y mueve Trailing / Profit Lock."""
        if symbol not in self.trades:
            return
        
        trade = self.trades[symbol]
        if trade.position_closed:
            return

        # --- 0. VIRTUAL STOP LOSS EMERGENCY (Vigilante Inteligente) ---
        virtual_sl_hit = (trade.side == "LONG" and price <= trade.stop_loss) or \
                         (trade.side == "SHORT" and price >= trade.stop_loss)
        if virtual_sl_hit:
            logger.error(f"[VIRTUAL SL] {symbol} cruzó el SL ({trade.stop_loss}) a {price}! BingX no lo ejecutó o faltaba la orden. ¡FORZANDO CIERRE DE EMERGENCIA!")
            await self.executor.close_position_market(symbol, trade.side, trade.remaining_size)
            
            # Aplicar cooldown
            if not trade.profit_lock_active and not trade.trailing_active:
                from app.config import Config
                from app.database.crud import set_cooldown
                await set_cooldown(symbol, Config.COOLDOWN_MINUTES)
                
            trade.position_closed = True
            await self.repo.mark_position_closed(symbol)
            self.trades.pop(symbol, None)
            from app.notifications.telegram import notifier
            asyncio.create_task(notifier.notify_close(symbol, trade.side, "Virtual Stop Loss Emergency"))
            return

        changed = False

        # --- 1. EVALUAR PROFIT LOCK (40% recorrido) ---
        if not trade.profit_lock_active:
            hit_lock = (trade.side == "LONG" and price >= trade.profit_lock_price) or \
                       (trade.side == "SHORT" and price <= trade.profit_lock_price)
            if hit_lock:
                strategy_name = getattr(trade, "strategy", "SMC_PRO")
                levels = self.risk.calculate_levels(trade.entry_price, trade.atr, trade.side, strategy_name)
                logger.info(f"🛡️ [SEGURO ACTIVADO] Breakeven (Colchón) activado en {symbol}. Asegurando ganancia.")
                trade.profit_lock_active = True
                trade.stop_loss = levels["lock_sl_price"]
                # Modificar Stop Loss
                await self.executor.cancel_order(symbol, trade.sl_order_id)
                trade.sl_order_id = await self.executor.place_stop_loss(symbol, trade.side, trade.remaining_size, trade.stop_loss)
                changed = True

        # --- 1.5. EVALUAR ACTIVACION DE TRAILING ---
        if not trade.trailing_active:
            strategy_name = getattr(trade, "strategy", "SMC_PRO")
            trailing_trigger = self.risk.calculate_levels(trade.entry_price, trade.atr, trade.side, strategy_name)["tp2_price"]
            if trailing_trigger > 0:
                hit_trailing = (trade.side == "LONG" and price >= trailing_trigger) or \
                               (trade.side == "SHORT" and price <= trailing_trigger)
                if hit_trailing:
                    logger.info(f"🛡️ [SEGURO ACTIVADO] Trailing Stop activado en {symbol} al tocar el trigger.")
                    trade.trailing_active = True
                    changed = True

        # --- 2. EVALUAR TRAILING STOP ---
        if trade.trailing_active:
            strategy_name = getattr(trade, "strategy", "SMC_PRO")
            dynamic_ema21 = getattr(trade, "dynamic_ema21", None) if strategy_name in ["SUPERTREND_EMA_MTF", "SUPERTREND_EMA_MTF_PRO"] else None
            levels = self.risk.calculate_levels(trade.entry_price, trade.atr, trade.side, strategy_name)
            
            new_sl, new_high, new_low = self.trailing.calculate_trailing_stop(
                trade.side, price, trade.highest_price, trade.lowest_price, trade.atr, trade.stop_loss, ema21_value=dynamic_ema21, trailing_dist_atr=levels.get("trailing_dist_atr", 1.2)
            )
            if new_high != trade.highest_price or new_low != trade.lowest_price:
                trade.highest_price = new_high
                trade.lowest_price = new_low
                changed = True

            if new_sl != trade.stop_loss:
                logger.info(f"[TRAILING] {symbol} moviendo SL a {new_sl:.6f}.")
                trade.stop_loss = new_sl
                await self.executor.cancel_order(symbol, trade.sl_order_id)
                trade.sl_order_id = await self.executor.place_stop_loss(symbol, trade.side, trade.remaining_size, trade.stop_loss)
                changed = True

        if changed:
            await self.repo.save_trade(trade)

    async def _on_order_fill(self, order_data: dict):
        """Registra llenados reales confirmados por el exchange."""
        symbol = order_data.get("s")
        if symbol not in self.trades: return
        trade = self.trades[symbol]
        
        o_type = order_data.get("o") # TAKE_PROFIT_MARKET, STOP_MARKET
        price_filled = float(order_data.get("p", 0))

        if o_type == "TAKE_PROFIT_MARKET":
            if not trade.tp1_filled:
                dist = self.risk.calculate_distribution(trade.position_size, getattr(trade, "strategy", "SMC_PRO"))
                logger.info(f"[TP1 FILLED] {symbol} TP1 cerrado.")
                trade.tp1_filled = True
                trade.remaining_size = trade.position_size - dist["tp1_qty"]
                
                # If there's no TP2, activate trailing immediately
                if dist["tp2_qty"] == 0.0:
                    trade.trailing_active = True
                    trade.tp2_filled = True # Virtual fill
                    await self.client.cancel_all_orders(symbol)
                    trade.highest_price = price_filled
                    trade.lowest_price = price_filled
                    
                    strategy_name = getattr(trade, "strategy", "SMC_PRO")
                    levels = self.risk.calculate_levels(trade.entry_price, trade.atr, trade.side, strategy_name)
                    new_sl, _, _ = self.trailing.calculate_trailing_stop(
                        trade.side, price_filled, trade.highest_price, trade.lowest_price, trade.atr, trade.stop_loss, trailing_dist_atr=levels.get("trailing_dist_atr", 1.2)
                    )
                    trade.stop_loss = new_sl
                    trade.sl_order_id = await self.executor.place_stop_loss(symbol, trade.side, trade.remaining_size, trade.stop_loss)

            elif not trade.tp2_filled:
                dist = self.risk.calculate_distribution(trade.position_size, getattr(trade, "strategy", "SMC_PRO"))
                logger.info(f"[TP2 FILLED] {symbol} TP2 cerrado. ACTIVANDO TRAILING.")
                trade.tp2_filled = True
                trade.trailing_active = True
                trade.remaining_size = trade.position_size - dist["tp1_qty"] - dist["tp2_qty"]
                # Cancelar órdenes pendientes y ajustar SL al restante con trailing
                await self.client.cancel_all_orders(symbol)
                # IniciaTrailing base: highest/lowest
                trade.highest_price = price_filled
                trade.lowest_price = price_filled
                
                strategy_name = getattr(trade, "strategy", "SMC_PRO")
                levels = self.risk.calculate_levels(trade.entry_price, trade.atr, trade.side, strategy_name)
                
                dynamic_ema21 = getattr(trade, "dynamic_ema21", None) if "SUPERTREND" in strategy_name else None
                new_sl, _, _ = self.trailing.calculate_trailing_stop(
                    trade.side, price_filled, trade.highest_price, trade.lowest_price, trade.atr, trade.stop_loss, ema21_value=dynamic_ema21, trailing_dist_atr=levels.get("trailing_dist_atr", 1.2)
                )
                trade.stop_loss = new_sl
                trade.sl_order_id = await self.executor.place_stop_loss(symbol, trade.side, trade.remaining_size, trade.stop_loss)
                
            await self.repo.save_trade(trade)

        elif o_type == "STOP_MARKET":
            pnl_est = 0.0
            if trade.side == "LONG": pnl_est = (price_filled - trade.entry_price) * trade.position_size
            else: pnl_est = (trade.entry_price - price_filled) * trade.position_size
            logger.info(f"🔴 [CERRANDO OPERACIÓN] {symbol} cerrada. PNL Estimado: {pnl_est:.4f} USDT | Razón: Stop Loss / Trailing Hit")
            
            # Si no tocó Profit Lock, ni Trailing... es una pérdida (SL original)
            if not trade.profit_lock_active and not trade.trailing_active:
                from app.config import Config
                from app.database.crud import set_cooldown
                logger.info(f"[COOLDOWN] {symbol} cerró en pérdida neta. Descansará por {Config.COOLDOWN_MINUTES} minutos.")
                await set_cooldown(symbol, Config.COOLDOWN_MINUTES)
                
            trade.position_closed = True
            await self.repo.mark_position_closed(symbol)
            self.trades.pop(symbol, None)
            asyncio.create_task(notifier.notify_close(symbol, trade.side, "Stop Loss / Trailing Hit"))

    async def open_trade(self, symbol: str, side: str, atr: float, price: float, strategy_name: str = "SMC_PRO"):
        """Punto de entrada cuando la estrategia dispara."""
        if not self.risk.can_open_trade(len(self.trades)): return

        # Update entry price to the real-time ticker to avoid price band errors (Code: 101211)
        ticker = await self.client.get_ticker(symbol)
        if ticker and "lastPrice" in ticker:
            price = float(ticker["lastPrice"])
            
        levels = self.risk.calculate_levels(price, atr, side, strategy_name)
        
        balance = await self.client.get_balance("USDT")
        stop_distance = abs(price - levels["sl_price"])
        size = self.risk.calculate_position_size(price, stop_distance, strategy_name, balance)
        
        # 1. Crear orden LIMIT cercana
        # 2. Esperar FILLED
        order_id = await self.executor.place_entry_limit(symbol, side, size, price)
        if not order_id: return

        # Esperaremos hasta 15 minutos (90 intentos de 10s) para que la orden Limit se llene.
        # Si no se llena en ese tiempo, la cancelamos para que no quede volando.
        for attempt in range(90):
            await asyncio.sleep(10)
            pos = await self.client.get_positions(symbol)
            for p in pos:
                actual_filled_size = abs(float(p.get("positionAmt", 0)))
                if actual_filled_size > 0:
                    logger.info(f"🟢 [ABRIENDO OPERACIÓN] Abriendo {side} en {symbol} | Estrategia: {strategy_name}")
                    
                    dist = self.risk.calculate_distribution(actual_filled_size, strategy_name)
                    
                    # Colocar SL inicial
                    sl_id = await self.executor.place_stop_loss(symbol, side, actual_filled_size, levels["sl_price"])
                    if not sl_id:
                        logger.error(f"[POSITION MANAGER] EMERGENCY! Failed to place SL for {symbol}. Market may have blown past! Closing at MARKET!")
                        await self.executor.close_position_market(symbol, side, actual_filled_size)
                        return
                        
                    # Colocar TP1 inicial (Solo si es SMC_PRO o tiene TP1)
                    if dist["tp1_qty"] > 0:
                        await self.executor.place_take_profit(symbol, side, dist["tp1_qty"], levels["tp1_price"])
                    # Colocar TP2 inicial
                    if dist["tp2_qty"] > 0:
                        await self.executor.place_take_profit(symbol, side, dist["tp2_qty"], levels["tp2_price"])

                    import uuid
                    trade = TradeState(
                        trade_id=str(uuid.uuid4()), symbol=symbol, side=side, entry_price=price,
                        position_size=actual_filled_size, atr=atr, stop_loss=levels["sl_price"],
                        tp1_price=levels["tp1_price"], tp2_price=levels["tp2_price"],
                        profit_lock_price=levels["lock_trigger_price"],
                        remaining_size=actual_filled_size, sl_order_id=sl_id,
                        strategy=strategy_name
                    )
                    await self.repo.save_trade(trade)
                    self.trades[symbol] = trade
                    await self.sync.subscribe_mark_price(symbol)
                    return
        logger.warning(f"[POSITION MANAGER] LIMIT order for {symbol} not filled within 15 minutos. Cancelling to avoid hanging.")
        await self.executor.cancel_order(symbol, order_id)
