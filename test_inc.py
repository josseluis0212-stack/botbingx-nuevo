import asyncio
from app.exchange.bingx_client import AsyncBingXClient
async def main():
    client = AsyncBingXClient()
    inc = await client.get_income(limit=5)
    print(inc)
asyncio.run(main())
