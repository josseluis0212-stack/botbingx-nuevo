import asyncio
from app.exchange.bingx_client import AsyncBingXClient
async def main():
    client = AsyncBingXClient()
    p = await client.get_contract_precisions()
    print('QAIT-USDT:', p.get('QAIT-USDT'))
    print('1000BONK-USDT:', p.get('1000BONK-USDT'))
asyncio.run(main())
