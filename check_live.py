import asyncio
from app.exchange.bingx_client import AsyncBingXClient
from app.strategy.supertrend_ema_mtf_pro import analyze as evaluate_supertrend_pro

async def check_live():
    client = AsyncBingXClient()
    symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT", "PEPE-USDT"]
    print("=== ESCÁNER EN VIVO: SUPERTREND EMA MTF PRO ===\\n")
    
    for symbol in symbols:
        result = await evaluate_supertrend_pro(client, symbol)
        signal = result.get('signal', 'NONE')
        print(f"Moneda: {symbol}")
        print(f"Señal Actual: {signal}")
        if 'debug' in result:
            print(f"Razones internas (Filtros): {result['debug']}")
        print("-" * 40)

if __name__ == "__main__":
    asyncio.run(check_live())
