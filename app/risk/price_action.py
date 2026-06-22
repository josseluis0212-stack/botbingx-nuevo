from app.logger import logger

class PriceActionFilter:
    """
    Inteligencia de Acción del Precio (Price Action) para filtrar operaciones engañosas
    donde el Stop Loss matemático (ATR) quedaría en una zona vulnerable frente a
    la estructura real del mercado (Pivotes / Soportes / Resistencias).
    """
    
    @staticmethod
    def get_swings(highs: list[float], lows: list[float], lookback: int = 40, left_bars: int = 3, right_bars: int = 3) -> tuple:
        """
        Detecta Soportes (Swing Lows) y Resistencias (Swing Highs) estructurales recientes.
        Devuelve listas de tuplas (indice, precio) ordenadas desde el más antiguo al más reciente.
        """
        if len(highs) < lookback:
            lookback = len(highs)
            
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        
        swing_highs = []
        swing_lows = []
        
        for i in range(left_bars, len(recent_highs) - right_bars):
            # Verificar Swing High (Pico rodeado de altos más bajos)
            is_swing_high = True
            for j in range(1, left_bars + 1):
                if recent_highs[i] <= recent_highs[i - j]: is_swing_high = False
            for j in range(1, right_bars + 1):
                if recent_highs[i] <= recent_highs[i + j]: is_swing_high = False
            if is_swing_high:
                swing_highs.append((i, recent_highs[i]))
                
            # Verificar Swing Low (Valle rodeado de bajos más altos)
            is_swing_low = True
            for j in range(1, left_bars + 1):
                if recent_lows[i] >= recent_lows[i - j]: is_swing_low = False
            for j in range(1, right_bars + 1):
                if recent_lows[i] >= recent_lows[i + j]: is_swing_low = False
            if is_swing_low:
                swing_lows.append((i, recent_lows[i]))
                
        return swing_highs, swing_lows

    @staticmethod
    def is_trade_safe(symbol: str, side: str, entry_price: float, sl_price: float, highs: list[float], lows: list[float]) -> bool:
        """
        Filtro de Sentido Común:
        Verifica si el Stop Loss matemático está protegido detrás del pivote estructural.
        Si el soporte real está más abajo que el SL (en LONG), la operación es una trampa y se rechaza.
        """
        swing_highs, swing_lows = PriceActionFilter.get_swings(highs, lows, lookback=40)
        
        if side == "LONG":
            # Extraer solo los precios de los Swing Lows válidos (por debajo de la entrada)
            valid_supports = [sl[1] for sl in swing_lows if sl[1] < entry_price]
            
            if not valid_supports:
                return True # No hay pivote claro, el mercado está en caída libre o subida vertical; confiamos en ATR
                
            # Tomamos el soporte MÁS RECIENTE (el último elemento de la lista)
            recent_support = valid_supports[-1]
            
            # Si nuestro Stop Loss matemático está POR ENCIMA del soporte real, es una TRAMPA.
            # Un pullback normal para testear el soporte tocará nuestro Stop Loss prematuramente.
            if sl_price > recent_support:
                logger.warning(f"[PRICE ACTION FILTER] {symbol} LONG rechazado! SL matemático ({sl_price}) es VULNERABLE. El soporte estructural (Swing Low) está en {recent_support}. ¡Es una trampa!")
                return False
                
        elif side == "SHORT":
            # Extraer solo los precios de los Swing Highs válidos (por encima de la entrada)
            valid_resistances = [sh[1] for sh in swing_highs if sh[1] > entry_price]
            
            if not valid_resistances:
                return True
                
            # Tomamos la resistencia MÁS RECIENTE
            recent_resistance = valid_resistances[-1]
            
            # Si nuestro Stop Loss matemático está POR DEBAJO de la resistencia real, es una TRAMPA.
            if sl_price < recent_resistance:
                logger.warning(f"[PRICE ACTION FILTER] {symbol} SHORT rechazado! SL matemático ({sl_price}) es VULNERABLE. La resistencia estructural (Swing High) está en {recent_resistance}. ¡Es una trampa!")
                return False
                
        return True
