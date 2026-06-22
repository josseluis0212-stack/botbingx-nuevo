import asyncio
from app.database.crud import TradeStateRepository, init_db

async def main():
    repo = TradeStateRepository()
    await init_db()
    trades = await TradeStateRepository.get_all_active_trades()
    for t in trades:
        if "AKE" in t.symbol:
            print(f"SYMBOL: {t.symbol}")
            print(f"ENTRY: {t.entry_price}")
            print(f"ATR: {t.atr}")
            print(f"PROFIT LOCK PRICE: {t.profit_lock_price}")
            print(f"PROFIT LOCK ACTIVE: {t.profit_lock_active}")
            print(f"TP1 HIT: {t.tp1_filled}")
            print(f"TRAILING ACTIVE: {t.trailing_active}")
            print(f"CURRENT SL: {t.stop_loss}")

asyncio.run(main())
