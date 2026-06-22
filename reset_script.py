import asyncio
import os
import sys

# Ensure app is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.exchange.bingx_client import AsyncBingXClient
from app.exchange.order_executor import OrderExecutionEngine

async def main():
    client = AsyncBingXClient()
    executor = OrderExecutionEngine(client)
    print("Fetching all positions...")
    positions = await client.get_positions()
    
    symbols_to_cancel = set()
    
    if positions:
        for p in positions:
            size = abs(float(p.get("positionAmt", 0)))
            if size > 0:
                symbol = p.get("symbol")
                side = "LONG" if str(p.get("positionSide", "")).upper() == "LONG" else "SHORT"
                print(f"Closing {side} {symbol} of size {size}...")
                await executor.close_position_market(symbol, side, size)
                symbols_to_cancel.add(symbol)
                
    print("Fetching top symbols to ensure no pending orders remain...")
    try:
        top_syms = await client.get_top_volume_symbols(200)
        for s in top_syms:
            symbols_to_cancel.add(s)
    except:
        pass
        
    print(f"Cancelling open orders for {len(symbols_to_cancel)} symbols...")
    for symbol in symbols_to_cancel:
        await client.cancel_all_orders(symbol)
        
    print("Deleting trades.db...")
    db_path = "storage/trades.db"
    if os.path.exists(db_path):
        os.remove(db_path)
        print("Database deleted.")
        
    print("Reset complete!")

if __name__ == "__main__":
    asyncio.run(main())
