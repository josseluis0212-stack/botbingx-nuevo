import asyncio
from app.exchange.bingx_client import AsyncBingXClient

async def force_reset():
    client = AsyncBingXClient()
    print('Fetching positions...')
    pos = await client.get_positions()
    closed_count = 0
    if pos:
        for p in pos:
            amt = abs(float(p.get('positionAmt', 0)))
            if amt > 0:
                sym = p.get('symbol')
                side = p.get('positionSide')
                print(f'Closing {sym} {side} amt={amt}...')
                pos_side = 'LONG' if side == 'LONG' else 'SHORT'
                close_side = 'SELL' if side == 'LONG' else 'BUY'
                await client.cancel_all_orders(sym)
                await client.place_order(symbol=sym, side=close_side, position_side=pos_side, order_type='MARKET', quantity=amt, reduce_only=False)
                closed_count += 1
                await asyncio.sleep(0.5)
    print(f'Closed {closed_count} positions.')
    import os
    import time
    import json
    from app.constants import POSITIONS_FILE, TRADES_FILE, PNL_OFFSET_FILE
    from app.config import Config
    
    if os.path.exists(POSITIONS_FILE): os.remove(POSITIONS_FILE)
    if os.path.exists(TRADES_FILE): os.remove(TRADES_FILE)
    
    pnl_start_time_file = os.path.join(Config.STORAGE_DIR, "pnl_start_time.txt")
    now_ms = int(time.time() * 1000)
    with open(pnl_start_time_file, "w") as f:
        f.write(str(now_ms))
        
    offset = {"pnl_today": 0.0, "pnl_week": 0.0, "pnl_month": 0.0, "pnl_total": 0.0}
    with open(PNL_OFFSET_FILE, "w") as f:
        json.dump(offset, f)
        
    print('Local state and PNL counters wiped.')

asyncio.run(force_reset())
