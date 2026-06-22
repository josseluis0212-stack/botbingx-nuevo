from app.logger import logger

class TakeProfitManager:
    @staticmethod
    def calculate_tps(entry_price: float, sl_price: float, total_size: float, side: str) -> list:
        """
        Calculates Tiered Take Profits for the Trifuerza Model.
        TP1 = 30% size at 1.2x Risk
        TP2 = 30% size at 2.0x Risk
        (The remaining 40% is left for the dynamic ATR trailing stop)
        """
        risk = abs(entry_price - sl_price)

        if side == "LONG":
            tp1_price = entry_price + (risk * 1.2)
            tp2_price = entry_price + (risk * 2.0)
        else:  # SHORT
            tp1_price = entry_price - (risk * 1.2)
            tp2_price = entry_price - (risk * 2.0)

        qty1 = round(total_size * 0.3, 4)
        qty2 = round(total_size * 0.3, 4)

        tps = [
            {"price": tp1_price, "qty": qty1, "level": 1, "pct": 30},
            {"price": tp2_price, "qty": qty2, "level": 2, "pct": 30}
        ]

        logger.info(f"[TP CALC] TP1={tp1_price:.6f}({qty1}) | TP2={tp2_price:.6f}({qty2})")
        return tps