import math
from app.logger import logger
from app.config import Config

class RiskManager:
    """
    Gestión matemática oficial de Riesgo.
    Implementa: SL = 2.5 ATR, TP_FINAL = 5 ATR.
    Distribución: TP1 (30% recorrido), LOCK (40% recorrido), TP2 (60% recorrido).
    """
    
    def __init__(self):
        self.position_margin = Config.POSITION_MARGIN
        self.leverage = Config.LEVERAGE
        self.max_open_trades = Config.MAX_OPEN_TRADES

    def can_open_trade(self, current_open_trades: int) -> bool:
        if current_open_trades >= self.max_open_trades:
            logger.info(f"[RISK] Max open trades reached ({self.max_open_trades}).")
            return False
        return True

    def calculate_position_size(self, entry_price: float) -> float:
        """
        Tamaño estático: Margen fijo x Apalancamiento = Volumen Total
        """
        if entry_price <= 0:
            return 0.0

        total_volume = self.position_margin * self.leverage
        size = total_volume / entry_price
        size = round(size, 6)
        return size

    @staticmethod
    def calculate_levels(entry_price: float, atr: float, side: str, strategy_name: str = "SMC_PRO") -> dict:
        """
        Calcula todos los niveles basados en el ATR y la estrategia.
        """
        if strategy_name == "SUPERTREND_EMA_MTF":
            sl_atr = 2.5
            tp_final_atr = 0.0 # No fixed TP
            tp1_atr = 0.0
            lock_atr = 2.0 # BE trigger
            lock_sl_atr = 0.0 # Move to entry
            tp2_atr = 2.5 # Trailing trigger
        else:
            sl_atr = 2.0          # Stop Loss en 2.0 ATR
            tp_final_atr = 4.0    # 100% del recorrido (R:R 1:2)
            
            tp1_atr = round(tp_final_atr * 0.30, 2)   # TP1 (30% de la distancia = 1.2 ATR)
            lock_atr = round(tp_final_atr * 0.333, 2) # Breakeven Trigger (33.3% de la distancia = ~1.33 ATR)
            lock_sl_atr = round(tp_final_atr * 0.15, 2) # Asegurar 15% (0.6 ATR)
            tp2_atr = round(tp_final_atr * 0.60, 2)   # TP2 y Trailing (60% de la distancia = 2.4 ATR)
        
        # Cap Stop Loss Distance to max 8.5% of entry price (to prevent Liquidation at 10x)
        max_sl_dist = entry_price * 0.085
        if sl_atr * atr > max_sl_dist:
            atr = max_sl_dist / sl_atr
        
        # Stop Loss
        if side == "LONG":
            sl_price = entry_price - (sl_atr * atr)
            tp_final = entry_price + (tp_final_atr * atr)
            tp1_price = entry_price + (tp1_atr * atr)
            tp2_price = entry_price + (tp2_atr * atr)
            lock_trigger = entry_price + (lock_atr * atr)
            lock_sl_price = entry_price + (lock_sl_atr * atr)
        else:
            sl_price = entry_price + (sl_atr * atr)
            tp_final = entry_price - (tp_final_atr * atr)
            tp1_price = entry_price - (tp1_atr * atr)
            tp2_price = entry_price - (tp2_atr * atr)
            lock_trigger = entry_price - (lock_atr * atr)
            lock_sl_price = entry_price - (lock_sl_atr * atr)

        return {
            "sl_price": sl_price,
            "tp_final_price": tp_final,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "lock_trigger_price": lock_trigger,
            "lock_sl_price": lock_sl_price
        }

    @staticmethod
    def calculate_distribution(total_size: float, strategy_name: str = "SMC_PRO") -> dict:
        """
        Distribuye la posición según estrategia.
        """
        if strategy_name == "SUPERTREND_EMA_MTF":
            return {
                "tp1_qty": 0.0,
                "tp2_qty": 0.0,
                "runner_qty": round(total_size, 6)
            }
            
        tp1_qty = round(total_size * 0.30, 6)
        tp2_qty = round(total_size * 0.30, 6)
        runner_qty = round(total_size - tp1_qty - tp2_qty, 6)

        return {
            "tp1_qty": tp1_qty,
            "tp2_qty": tp2_qty,
            "runner_qty": runner_qty
        }