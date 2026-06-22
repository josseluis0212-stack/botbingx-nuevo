from collections import deque
from app.constants import MAX_BUFFER_SIZE
from app.logger import logger


class CandleBuffer:
    """
    Circular buffer of OHLCV candles using deque for efficiency.
    Handles in-progress candle updates (same timestamp = update, new timestamp = append).
    """

    def __init__(self, maxlen=MAX_BUFFER_SIZE):
        self.candles = deque(maxlen=maxlen)

    def add_candle(self, candle: dict):
        """
        Add or update a candle.
        If same timestamp as last candle, replaces it (live update).
        If newer timestamp, marks last as closed and appends new.
        """
        if not self.candles:
            self.candles.append(candle)
            return

        last = self.candles[-1]
        if candle["time"] == last["time"]:
            self.candles[-1] = candle
        elif candle["time"] > last["time"]:
            last_updated = dict(last)
            last_updated["closed"] = True
            self.candles[-1] = last_updated
            self.candles.append(candle)

    def get_recent(self, count: int = 17):
        """Returns the last `count` candles, or None if not enough data."""
        if len(self.candles) < count:
            return None
        return list(self.candles)[-count:]

    def __len__(self):
        return len(self.candles)