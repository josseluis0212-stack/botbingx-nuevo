import asyncio
from app.exchange.bingx_client import AsyncBingXClient

class PositionManager:
    """
    Manages per-symbol locks to prevent race conditions.
    Provides real-time position queries from the exchange.
    """
    def __init__(self):
        self.client = AsyncBingXClient()
        self.locks: dict = {}

    def get_lock(self, symbol: str) -> asyncio.Lock:
        if symbol not in self.locks:
            self.locks[symbol] = asyncio.Lock()
        return self.locks[symbol]

    async def get_open_position(self, symbol: str) -> dict:
        """Returns the open position dict for the symbol, or empty dict."""
        positions = await self.client.get_positions(symbol)
        if not positions:
            return {}
        for pos in positions:
            amt = float(pos.get("positionAmt", 0))
            if abs(amt) > 0:
                return pos
        return {}