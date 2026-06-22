import asyncio
from app.exchange.bingx_client import AsyncBingXClient
from app.exchange.order_executor import OrderExecutor

async def main():
    client = AsyncBingXClient()
    executor = OrderExecutor()
    positions = await client.get_positions()
    print("Found positions:", len(positions))
    for p in positions:
        sym = p.get("symbol")
        side = p.get("positionSide")
        amt = abs(float(p.get("positionAmt", 0)))
        if amt > 0:
            print(f"Closing {sym} {side} amt={amt}")
            await executor.close_position_market(sym, side)
    
    print("Done")

if __name__ == "__main__":
    asyncio.run(main())
