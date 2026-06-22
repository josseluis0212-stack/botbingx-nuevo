import asyncio
from app.exchange.bingx_client import AsyncBingXClient
from app.strategy.quantum_v10_pro import evaluate_v10_pro
from app.strategy.supertrend_pullback import evaluate_supertrend_pullback

async def test():
    client = AsyncBingXClient()
    
    # Test top 5 volume coins
    coins = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "PEPE-USDT", "DOGE-USDT"]
    
    print("--- SMC V10 PRO ---")
    for coin in coins:
        res = await evaluate_v10_pro(client, coin)
        print(f"{coin}: {res}")
        
    print("--- SUPERTREND PULLBACK ---")
    for coin in coins:
        res = await evaluate_supertrend_pullback(client, coin)
        print(f"{coin}: {res}")

if __name__ == "__main__":
    asyncio.run(test())
