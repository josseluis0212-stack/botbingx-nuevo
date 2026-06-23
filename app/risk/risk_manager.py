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

    def calculate_position_size(self, entry_price: float, stop_distance: float = 0.0, strategy_name: str = "SMC_PRO", account_balance: float = 0.0) -> float:
        """
        Tamaño dinámico para PRO (Riesgo 1%) o estático para SMC.
        Ahora modificado para usar un apalancamiento fijo (15 USDT al 10x = 150 USDT volumen).
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
        if strategy_name == "SUPERTREND_EMA_MTF_PRO":
            sl_atr = 2.5
            tp_final_atr = 0.0
            tp1_atr = 0.0
            lock_atr = 2.0 # BE trigger
            lock_sl_atr = 0.0 # Move to entry
            tp2_atr = 2.5 # Trailing trigger
            trailing_dist_atr = 1.2
        elif strategy_name == "SUPERTREND_EMA_MTF":
            sl_atr = 2.0
            tp_final_atr = 0.0 # No fixed TP
            tp1_atr = 0.0
            lock_atr = 1.0 # BE trigger
            lock_sl_atr = 0.2 # Move to 10% profit
            tp2_atr = 2.0 # Trailing trigger
            trailing_dist_atr = 1.2
        elif "LIQ" in strategy_name or "SWEEP" in strategy_name:
            sl_atr = 1.0          # Ajustado para barridos de liquidez (1:3 max)
            tp_final_atr = 3.0    
            tp1_atr = 2.0         # TP1 al 2.0
            lock_atr = 1.0        # BE Trigger muy agresivo
            lock_sl_atr = 0.1     # Asegurar comisiones
            tp2_atr = 2.0         # Trailing Trigger
            trailing_dist_atr = 1.0
        elif "AMD" in strategy_name or "BUSTOS" in strategy_name:
            sl_atr = 1.5          # Holgura estándar para pullbacks
            tp_final_atr = 0.0    # SIN TP FINAL
            tp1_atr = 0.0         # SIN TP1
            lock_atr = 1.5        # BE Trigger
            lock_sl_atr = 0.1     # Asegurar comisiones
            tp2_atr = 1.5         # Trailing Trigger rápido
            trailing_dist_atr = 1.5
        elif "FVG" in strategy_name or "OB" in strategy_name:
            sl_atr = 1.5          # Detrás del FVG/OB
            tp_final_atr = 4.0    
            tp1_atr = 2.0         # TP1 
            lock_atr = 2.0        # BE Trigger conservador
            lock_sl_atr = 0.1     # Asegurar comisiones
            tp2_atr = 2.0         # Trailing Trigger
            trailing_dist_atr = 1.5
        else:
            sl_atr = 1.5          # Genérico
            tp_final_atr = 3.0    
            tp1_atr = 1.5         
            lock_atr = 1.5        
            lock_sl_atr = 0.5     
            tp2_atr = 2.0         
            trailing_dist_atr = 1.5
        
        # Cap Stop Loss Distance to max 8.5% of entry price (to prevent Liquidation at 10x)
        max_sl_dist = entry_price * 0.085
        if sl_atr * atr > max_sl_dist:
            atr = max_sl_dist / sl_atr
            
        from app.config import Config
        target_roe = 0.15
        price_change_for_roe = (target_roe / Config.LEVERAGE) * entry_price
        
        # Stop Loss
        if side == "LONG":
            sl_price = entry_price - (sl_atr * atr)
            tp_final = entry_price + (tp_final_atr * atr)
            tp1_price = entry_price + (tp1_atr * atr)
            tp2_price = entry_price + (tp2_atr * atr)
            lock_trigger = entry_price + (lock_atr * atr)
            
            if strategy_name == "SUPERTREND_EMA_MTF_PRO":
                lock_sl_price = entry_price + price_change_for_roe
            else:
                lock_sl_price = entry_price + (lock_sl_atr * atr)
        else:
            sl_price = entry_price + (sl_atr * atr)
            tp_final = entry_price - (tp_final_atr * atr)
            tp1_price = entry_price - (tp1_atr * atr)
            tp2_price = entry_price - (tp2_atr * atr)
            lock_trigger = entry_price - (lock_atr * atr)
            
            if strategy_name == "SUPERTREND_EMA_MTF_PRO":
                lock_sl_price = entry_price - price_change_for_roe
            else:
                lock_sl_price = entry_price - (lock_sl_atr * atr)

        return {
            "sl_price": sl_price,
            "tp_final_price": tp_final,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "lock_trigger_price": lock_trigger,
            "lock_sl_price": lock_sl_price,
            "trailing_dist_atr": trailing_dist_atr
        }

    @staticmethod
    def calculate_distribution(total_size: float, strategy_name: str = "SMC_PRO") -> dict:
        """
        Distribuye la posición según estrategia.
        """
        if strategy_name in ["SUPERTREND_EMA_MTF", "SUPERTREND_EMA_MTF_PRO"] or "AMD" in strategy_name or "BUSTOS" in strategy_name:
            return {
                "tp1_qty": 0.0,
                "tp2_qty": 0.0,
                "runner_qty": round(total_size, 6)
            }
            
        if "LIQ" in strategy_name or "SWEEP" in strategy_name or "FVG" in strategy_name or "OB" in strategy_name or "SMC_PRO" in strategy_name:
            tp1_qty = round(total_size, 6) # 100% al target estructural
            tp2_qty = 0.0
            runner_qty = 0.0
            return {
                "tp1_qty": tp1_qty,
                "tp2_qty": tp2_qty,
                "runner_qty": runner_qty
            }
            
        tp1_qty = round(total_size * 0.30, 6)
        tp2_qty = round(total_size * 0.30, 6)
        runner_qty = round(total_size - tp1_qty - tp2_qty, 6)

        return {
            "tp1_qty": tp1_qty,
            "tp2_qty": tp2_qty,
            "runner_qty": runner_qty
        }