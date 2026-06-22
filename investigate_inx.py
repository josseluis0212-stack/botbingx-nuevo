import asyncio
from app.exchange.bingx_client import AsyncBingXClient

async def check():
    client = AsyncBingXClient()
    orders = await client.get_open_orders('INX-USDT')
    print('--- INX-USDT Open Orders ---')
    for o in orders:
        print(f"{o.get('type')} {o.get('side')} Qty:{o.get('origQty')} Stop:{o.get('stopPrice')}")
    print('--- INX-USDT Positions ---')
    pos = await client.get_positions()
    for p in pos:
        if p.get('symbol') == 'INX-USDT':
            print(p)

asyncio.run(check())
