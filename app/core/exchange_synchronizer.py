import asyncio
import time
from app.exchange.bingx_client import AsyncBingXClient
from app.logger import logger

class ExchangeSynchronizer:
    """
    Gestiona la conexión WebSocket de forma ininterrumpida y provee callbacks al PositionManager.
    No toma decisiones lógicas, solo sincroniza datos con tolerancia a fallos.
    """
    
    def __init__(self, client: AsyncBingXClient):
        self.client = client
        self.running = False
        self.price_callbacks = []
        self.fill_callbacks = []
        self._ws_task = None
        self._price_cache = {}

    def register_price_callback(self, callback):
        self.price_callbacks.append(callback)

    def register_fill_callback(self, callback):
        self.fill_callbacks.append(callback)

    async def start(self):
        self.running = True
        # WebSocket is currently unimplemented in bingx_client.py
        # Relying entirely on HTTP Fallback in Supervisor Loop.
        logger.info("[SYNC] Exchange Synchronizer Started (HTTP Polling Mode).")

    async def stop(self):
        self.running = False
        logger.info("[SYNC] Exchange Synchronizer Stopped.")

    async def _on_ws_message(self, data: dict):
        """Routes incoming raw WS messages to the registered callbacks."""
        try:
            # Mark Price Update
            if "dataType" in data and "markPrice" in data["dataType"]:
                if "data" in data and isinstance(data["data"], list):
                    for item in data["data"]:
                        symbol = item.get("s", item.get("symbol"))
                        price_str = item.get("p", item.get("markPrice"))
                        if symbol and price_str:
                            price = float(price_str)
                            self._price_cache[symbol] = price
                            for cb in self.price_callbacks:
                                asyncio.create_task(cb(symbol, price))
            
            # User Data Stream (Order Fills)
            elif data.get("e") == "ORDER_TRADE_UPDATE":
                order_info = data.get("o", {})
                status = order_info.get("X", "") # X = Order Status (FILLED, CANCELED, etc)
                if status == "FILLED":
                    for cb in self.fill_callbacks:
                        asyncio.create_task(cb(order_info))

        except Exception as e:
            logger.error(f"[SYNC] Error processing WS message: {e}")

    def get_cached_price(self, symbol: str) -> float:
        return self._price_cache.get(symbol, 0.0)

    async def subscribe_mark_price(self, symbol: str):
        # HTTP Fallback handles price updates automatically
        pass
