from app.logger import logger

class TrailingManager:
    """
    Gestión del 40% restante a través de Trailing Stop dinámico.
    Distancia: 1.2 ATR.
    El Trailing Stop NUNCA debe retroceder.
    """

    @staticmethod
    def calculate_trailing_stop(side: str, current_price: float, highest_price: float, lowest_price: float, atr: float, current_sl: float, ema21_value: float = None) -> tuple:
        """
        Calcula el Trailing Stop oficial de 1.2 ATR o usa la EMA21 si se especifica.
        """
        trailing_dist = 1.2 * atr
        
        # Ensure peaks are initialized
        if highest_price is None or highest_price == 0:
            highest_price = current_price
        if lowest_price is None or lowest_price == 0:
            lowest_price = current_price

        new_sl = current_sl

        if side == "LONG":
            highest_price = max(highest_price, current_price)
            if ema21_value is not None and ema21_value > 0:
                calculated_sl = ema21_value
            else:
                calculated_sl = highest_price - trailing_dist
            
            # EL TRAILING NUNCA DEBE RETROCEDER
            if calculated_sl > current_sl:
                new_sl = calculated_sl

        elif side == "SHORT":
            lowest_price = min(lowest_price, current_price)
            if ema21_value is not None and ema21_value > 0:
                calculated_sl = ema21_value
            else:
                calculated_sl = lowest_price + trailing_dist
            
            # EL TRAILING NUNCA DEBE RETROCEDER (en short, menor precio es mejor)
            if current_sl == 0 or calculated_sl < current_sl:
                new_sl = calculated_sl

        return new_sl, highest_price, lowest_price
