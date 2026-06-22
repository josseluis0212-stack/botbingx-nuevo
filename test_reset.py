import asyncio
from app.core.engine import Engine
from app.exchange.bingx_client import AsyncBingXClient
from app.exchange.websocket_client import BingXWebSocket

async def test():
    client = AsyncBingXClient()
    e = Engine(client, BingXWebSocket(client))
    await e.reset_state()

asyncio.run(test())
