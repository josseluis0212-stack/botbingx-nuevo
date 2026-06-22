import asyncio
from app.exchange.bingx_client import AsyncBingXClient
async def main():
    client = AsyncBingXClient()
    res = await client._request('GET', '/openApi/swap/v2/quote/contracts', signed=False)
    if res and 'data' in res:
        print(res['data'][0])
asyncio.run(main())
