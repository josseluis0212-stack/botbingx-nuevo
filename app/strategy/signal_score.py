def calculate_score(candles: list, signal_data: dict) -> int:
    """
    Calculates signal quality score (0-100).
    Only signals with score >= 70 are traded.
    """
    if signal_data["signal"] == "NONE":
        return 0

    if len(candles) < 2:
        return 0
        
    score = 0
    sweep = candles[-2]
    confirm = candles[-1]
    signal = signal_data["signal"]

    # +30 pts: Confirm volume > sweep volume (institutional absorption)
    if confirm.get("volume", 0) > sweep.get("volume", 0):
        score += 30

    # +30 pts: Strong rejection (body covers >50% of sweep range)
    sweep_range = sweep["high"] - sweep["low"]
    if sweep_range > 0:
        if signal == "LONG":
            rejection = confirm["close"] - sweep["low"]
        else:
            rejection = sweep["high"] - confirm["close"]

        if rejection > sweep_range * 0.50:
            score += 30

    # +20 pts: Confirm candle body is bullish/bearish (closes in right direction)
    if signal == "LONG" and confirm["close"] > confirm["open"]:
        score += 20
    elif signal == "SHORT" and confirm["close"] < confirm["open"]:
        score += 20

    # +20 pts: Confirm close is in the top/bottom 30% of its own range
    candle_range = confirm["high"] - confirm["low"]
    if candle_range > 0:
        if signal == "LONG":
            pos = (confirm["close"] - confirm["low"]) / candle_range
            if pos > 0.70:
                score += 20
        else:
            pos = (confirm["high"] - confirm["close"]) / candle_range
            if pos > 0.70:
                score += 20

    return score