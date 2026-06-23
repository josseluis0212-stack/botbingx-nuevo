from app.logger import logger

class VolumeFilter:
    """
    Filtros de Volumen personalizados por estrategia.
    Cada estrategia tiene su propia firma volumétrica institucional.
    """

    @staticmethod
    def _avg_volume(volumes: list[float], lookback: int = 20) -> float:
        """Calcula el volumen promedio de las últimas N velas (excluyendo la actual)."""
        if len(volumes) < lookback + 1:
            return 0.0
        return sum(volumes[-(lookback + 1):-1]) / lookback

    @staticmethod
    def _wick_ratio(candle: dict) -> float:
        """
        Calcula qué porcentaje del rango total de la vela es mecha.
        Para LONG: mecha inferior / rango. Para SHORT: mecha superior / rango.
        """
        high = float(candle.get("high", 0))
        low  = float(candle.get("low", 0))
        op   = float(candle.get("open", 0))
        cl   = float(candle.get("close", 0))
        rng  = high - low
        if rng == 0:
            return 0.0
        body_top = max(op, cl)
        body_bot = min(op, cl)
        upper_wick = (high - body_top) / rng
        lower_wick = (body_bot - low) / rng
        return upper_wick, lower_wick

    @staticmethod
    def _body_ratio(candle: dict) -> float:
        """Calcula qué porcentaje del rango total es el cuerpo."""
        high = float(candle.get("high", 0))
        low  = float(candle.get("low", 0))
        op   = float(candle.get("open", 0))
        cl   = float(candle.get("close", 0))
        rng  = high - low
        if rng == 0:
            return 0.0
        body = abs(cl - op)
        return body / rng

    # ─────────────────────────────────────────────────────────────
    # 1. LIQUIDITY SWEEP
    #    Spike ≥ 1.8x + mecha ≥ 45% del rango (rechazo agresivo institucional)
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def check_liquidity_sweep(symbol: str, side: str, klines: list[dict], volumes: list[float]) -> bool:
        avg = VolumeFilter._avg_volume(volumes)
        if avg == 0:
            return True
        signal_vol = volumes[-1]
        ratio = signal_vol / avg

        candle = klines[-1]
        upper_wick, lower_wick = VolumeFilter._wick_ratio(candle)
        # Para LONG (barrido de lows): verificar mecha inferior
        # Para SHORT (barrido de highs): verificar mecha superior
        rejection_wick = lower_wick if side == "LONG" else upper_wick

        if ratio < 1.5:
            logger.warning(f"[VOL:LIQ_SWEEP] {symbol} {side} RECHAZADO — Spike de volumen insuficiente: {ratio:.2f}x (mínimo 1.5x)")
            return False
        if rejection_wick < 0.40:
            logger.warning(f"[VOL:LIQ_SWEEP] {symbol} {side} RECHAZADO — Mecha de rechazo débil: {rejection_wick:.1%} (mínimo 40%)")
            return False

        logger.info(f"[VOL:LIQ_SWEEP] {symbol} {side} ✅ Vol={ratio:.2f}x | Mecha={rejection_wick:.1%}")
        return True

    # ─────────────────────────────────────────────────────────────
    # 2. FVG (Fair Value Gap — SMC Pro)
    #    Moderado 1.2x–3.0x + cuerpo ≥ 50% (llenado limpio)
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def check_fvg(symbol: str, side: str, klines: list[dict], volumes: list[float]) -> bool:
        avg = VolumeFilter._avg_volume(volumes)
        if avg == 0:
            return True
        signal_vol = volumes[-1]
        ratio = signal_vol / avg

        candle = klines[-1]
        body = VolumeFilter._body_ratio(candle)

        if ratio < 0.4 or ratio > 3.0:
            logger.warning(f"[VOL:FVG] {symbol} {side} RECHAZADO — Volumen fuera de rango: {ratio:.2f}x (esperado 0.4x–3.0x)")
            return False
        if body < 0.30:
            logger.warning(f"[VOL:FVG] {symbol} {side} RECHAZADO — Cuerpo de vela insuficiente: {body:.1%} (mínimo 30%). Mecha domina.")
            return False

        logger.info(f"[VOL:FVG] {symbol} {side} ✅ Vol={ratio:.2f}x | Cuerpo={body:.1%}")
        return True

    # ─────────────────────────────────────────────────────────────
    # 3. ORDER BLOCK RETEST (SMC Pro — OB)
    #    Llegada silenciosa ≤ 0.9x + rebote explosivo ≥ 1.5x
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def check_ob_retest(symbol: str, side: str, klines: list[dict], volumes: list[float]) -> bool:
        avg = VolumeFilter._avg_volume(volumes)
        if avg == 0:
            return True

        # Vela de llegada al OB = penúltima vela
        arrival_vol   = volumes[-2] if len(volumes) >= 2 else volumes[-1]
        # Vela de rebote (confirmación) = última vela
        rejection_vol = volumes[-1]

        arrival_ratio   = arrival_vol   / avg
        rejection_ratio = rejection_vol / avg

        if arrival_ratio > 1.2:
            logger.warning(f"[VOL:OB_RETEST] {symbol} {side} RECHAZADO — Llegada al OB con demasiado volumen: {arrival_ratio:.2f}x (esperado ≤ 1.2x, precio 'agotado' es sospechoso)")
            return False
        if rejection_ratio < 1.25:
            logger.warning(f"[VOL:OB_RETEST] {symbol} {side} RECHAZADO — Rebote débil desde el OB: {rejection_ratio:.2f}x (esperado ≥ 1.25x. Sin defensa institucional.)")
            return False

        logger.info(f"[VOL:OB_RETEST] {symbol} {side} ✅ Llegada={arrival_ratio:.2f}x (silenciosa) | Rebote={rejection_ratio:.2f}x (explosivo)")
        return True

    # ─────────────────────────────────────────────────────────────
    # 4. AMD — Bustos Pullback
    #    Sweep ≥ 2.0x + distribución ≥ 1.3x + rango comprimido previo
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def check_amd(symbol: str, side: str, klines: list[dict], volumes: list[float]) -> bool:
        avg = VolumeFilter._avg_volume(volumes)
        if avg == 0:
            return True

        # Vela de sweep/trampa: buscar la de mayor volumen en últimas 5 velas
        recent_vols = volumes[-6:-1]
        sweep_vol   = max(recent_vols) if recent_vols else volumes[-2]
        # Vela de distribución/confirmación: la actual
        dist_vol    = volumes[-1]

        sweep_ratio = sweep_vol / avg
        dist_ratio  = dist_vol  / avg

        # Verificar rango comprimido previo: ATR de las 10 velas anteriores vs 20 totales
        if len(klines) >= 20:
            older_klines = klines[-20:-10]
            recent_klines = klines[-10:]
            older_ranges = [float(k["high"]) - float(k["low"]) for k in older_klines]
            recent_ranges = [float(k["high"]) - float(k["low"]) for k in recent_klines]
            older_avg_range  = sum(older_ranges) / len(older_ranges) if older_ranges else 1
            recent_avg_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else 1
            compressed = recent_avg_range < older_avg_range * 0.75  # Rango reciente 25% más comprimido
        else:
            compressed = True  # No hay datos suficientes, asumir válido

        if sweep_ratio < 1.8:
            logger.warning(f"[VOL:AMD] {symbol} {side} RECHAZADO — Sweep sin volumen institucional: {sweep_ratio:.2f}x (mínimo 1.8x)")
            return False
        if dist_ratio < 1.3:
            logger.warning(f"[VOL:AMD] {symbol} {side} RECHAZADO — Distribución débil: {dist_ratio:.2f}x (mínimo 1.3x)")
            return False
        if not compressed:
            logger.warning(f"[VOL:AMD] {symbol} {side} RECHAZADO — Sin rango comprimido previo. Patrón AMD no válido.")
            return False

        logger.info(f"[VOL:AMD] {symbol} {side} ✅ Sweep={sweep_ratio:.2f}x | Dist={dist_ratio:.2f}x | Rango comprimido=✅")
        return True

    # ─────────────────────────────────────────────────────────────
    # 5. SUPERTREND + EMA MTF
    #    Pendiente de volumen positiva + ratio ≥ 1.1x
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def check_supertrend_ema(symbol: str, side: str, klines: list[dict], volumes: list[float]) -> bool:
        avg = VolumeFilter._avg_volume(volumes)
        if avg == 0:
            return True
        signal_vol = volumes[-1]
        ratio = signal_vol / avg

        # Pendiente de volumen: promedio de las últimas 5 velas vs las 5 anteriores
        if len(volumes) >= 11:
            recent_5 = sum(volumes[-6:-1]) / 5
            prior_5  = sum(volumes[-11:-6]) / 5
            slope_positive = recent_5 > prior_5
        else:
            slope_positive = True  # Asumir válido si no hay suficientes datos

        if ratio < 1.0:
            logger.warning(f"[VOL:ST_EMA] {symbol} {side} RECHAZADO — Volumen sin combustible: {ratio:.2f}x (mínimo 1.0x)")
            return False
        if not slope_positive:
            logger.warning(f"[VOL:ST_EMA] {symbol} {side} RECHAZADO — Pendiente de volumen negativa. La tendencia pierde combustible.")
            return False

        logger.info(f"[VOL:ST_EMA] {symbol} {side} ✅ Vol={ratio:.2f}x | Pendiente positiva=✅")
        return True

    # ─────────────────────────────────────────────────────────────
    # Punto de entrada principal: despacha al checker correcto
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def is_volume_valid(symbol: str, side: str, strategy_name: str, klines: list[dict], volumes: list[float]) -> bool:
        """
        Dispatcher que selecciona el filtro de volumen correcto según la estrategia.
        """
        if "LIQ" in strategy_name or "SWEEP" in strategy_name:
            return VolumeFilter.check_liquidity_sweep(symbol, side, klines, volumes)
        elif "SMC" in strategy_name or "FVG" in strategy_name or "OB" in strategy_name:
            if "AMD" in strategy_name:
                return VolumeFilter.check_amd(symbol, side, klines, volumes)
            if "OB" in strategy_name:
                return VolumeFilter.check_ob_retest(symbol, side, klines, volumes)
            
            # Si no especifica explícitamente FVG u OB, distinguimos por firma de volumen
            if "FVG" not in strategy_name:
                avg = VolumeFilter._avg_volume(volumes)
                if avg > 0 and len(volumes) >= 2:
                    arrival_ratio = volumes[-2] / avg
                    if arrival_ratio <= 0.9:
                        return VolumeFilter.check_ob_retest(symbol, side, klines, volumes)
            return VolumeFilter.check_fvg(symbol, side, klines, volumes)
        elif "BUSTOS" in strategy_name or "AMD" in strategy_name:
            return VolumeFilter.check_amd(symbol, side, klines, volumes)
        elif "SUPERTREND" in strategy_name or "ST" in strategy_name:
            return VolumeFilter.check_supertrend_ema(symbol, side, klines, volumes)
        else:
            # Fallback genérico: ratio ≥ 1.2x
            avg = VolumeFilter._avg_volume(volumes)
            if avg > 0:
                ratio = volumes[-1] / avg
                if ratio < 1.1:
                    logger.warning(f"[VOL:GENERIC] {symbol} {side} RECHAZADO — Volumen bajo: {ratio:.2f}x")
                    return False
            return True
