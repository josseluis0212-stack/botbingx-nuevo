import asyncio
import os
from app.exchange.bingx_client import AsyncBingXClient
from app.strategy.smc_pro_v1 import analyze

async def run_test():
    client = AsyncBingXClient()
    symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT", "PEPE-USDT", "ORDI-USDT"]
    print("Iniciando diagnostico de SMC PRO V1 en 7 pares top...")
    
    for symbol in symbols:
        result = await analyze(client, symbol)
        print(f"{symbol}: {result}")
        
    await client.close()

if __name__ == "__main__":
    asyncio.run(run_test())
