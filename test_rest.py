import asyncio
import json
from app.exchange.bingx_client import AsyncBingXClient

async def main():
    print("Initializing AsyncBingXClient...")
    client = AsyncBingXClient()
    
    print("\n--- 1. Fetching VST Balance ---")
    # Try v2 balance
    balance_res = await client._request("GET", "/openApi/swap/v2/user/balance", signed=True)
    if not balance_res.get("success"):
        # Try v3 balance if v2 fails
        balance_res = await client._request("GET", "/openApi/swap/v3/user/balance", signed=True)
    
    print("Balance Response:")
    print(json.dumps(balance_res, indent=2))
    
    print("\n--- 2. Placing dummy LIMIT postOnly order on BTC-USDT ---")
    order_res = await client.place_order(
        symbol="BTC-USDT",
        side="BUY",
        position_side="LONG",
        order_type="LIMIT",
        quantity=0.0001,
        price=30000.0,
        post_only=True
    )
    print("Order Response:")
    print(json.dumps(order_res, indent=2))
    
    if order_res.get("success"):
        print("\n--- 3. Cancelling all orders for BTC-USDT ---")
        cancel_res = await client.cancel_all_orders("BTC-USDT")
        print(f"Cancel Response: {cancel_res}")

if __name__ == "__main__":
    asyncio.run(main())
