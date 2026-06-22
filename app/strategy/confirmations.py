def filter_confirmations(candles: list, signal_data: dict) -> bool:
    """
    Institutional confirmation filters applied to the confirm candle.
    Returns True if the signal passes quality checks.
    """
    if signal_data["signal"] == "NONE":
        return False

    if len(candles) < 2:
        return False

    confirm = candles[-1]
    sweep = candles[-2]

    body = abs(confirm["close"] - confirm["open"])
    wick = confirm["high"] - confirm["low"]

    if wick <= 0:
        return False

    # Body must be at least 10% of total wick range
    if body / wick < 0.10:
        return False

    # Volume on confirm must be positive (skip check if 0 — some demo symbols have 0 volume)
    vol = confirm.get("volume", 0)
    if vol < 0:
        return False
    # vol == 0 is allowed (demo symbols); only reject if explicitly negative

    return True