import asyncio
from app.exchange.bingx_client import AsyncBingXClient

async def test_reduce_only():
    client = AsyncBingXClient()
    
    # Check balance
    bal = await client.get_balance()
    print(f"Balance: {bal}")
    
    # Get current price
    klines = await client.get_klines("BTC-USDT", "5m", 1)
    if not klines:
        print("Failed to get klines")
        return
        
    current_price = klines[0]['close']
    print(f"Current BTC price: {current_price}")
    
    # Test placing a STOP_MARKET order with reduce_only=True
    res = await client.place_order(
        symbol="BTC-USDT",
        side="SELL",
        position_side="LONG",
        order_type="STOP_MARKET",
        quantity=0.001,
        stop_price=current_price - 1000,
        reduce_only=True
    )
    print(f"Response: {res}")
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(test_reduce_only())
