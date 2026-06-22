import asyncio, sys, json
sys.path.insert(0, '.')
from app.exchange.bingx_client import AsyncBingXClient

async def check_account():
    client = AsyncBingXClient()
    positions = await client.get_positions()
    print('--- OPEN POSITIONS ---')
    for p in positions:
        amt = float(p.get('positionAmt', 0))
        if abs(amt) > 0:
            print(f"{p.get('symbol')}: {amt} | Entry: {p.get('avgPrice')}")
            
    print('\n--- OPEN ORDERS (Pending TP/SL/Limits) ---')
    for sym in ['ETH-USDT', 'DOGE-USDT', 'XRP-USDT', 'BTC-USDT']:
        orders = await client.get_open_orders(sym)
        if orders:
            print(f'>> {sym}:')
            for o in orders:
                print(f"  [{o.get('type')}] {o.get('side')} {o.get('positionSide')} | Price: {o.get('price')} | Trigger: {o.get('stopPrice', 'N/A')}")

asyncio.run(check_account())
