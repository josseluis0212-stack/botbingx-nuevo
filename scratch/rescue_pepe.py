import asyncio
import sys
sys.path.insert(0, '.')
from app.exchange.bingx_client import AsyncBingXClient
from app.risk.takeprofit_manager import TakeProfitManager

async def rescue():
    client = AsyncBingXClient()
    tp_manager = TakeProfitManager()
    
    symbol = "1000PEPE-USDT"
    print(f"Rescuing {symbol}...")
    
    positions = await client.get_positions(symbol)
    if not positions:
        print("No positions found.")
        return
        
    target_pos = None
    for p in positions:
        amt = abs(float(p.get("positionAmt", 0)))
        if amt > 0:
            target_pos = p
            break
            
    if not target_pos:
        print("No active position for 1000PEPE-USDT.")
        return
        
    size = abs(float(target_pos["positionAmt"]))
    entry_price = float(target_pos["avgPrice"])
    side = target_pos["positionSide"] # SHORT or LONG
    
    print(f"Active Position: {side} | Size: {size} | Entry Price: {entry_price}")
    
    pos_side = "LONG" if side == "LONG" else "SHORT"
    close_side = "SELL" if side == "LONG" else "BUY"
    
    # Calculate SL and TPs
    # Standard SL distance is 10% for orphan positions
    sl_price = entry_price * 0.9 if side == "LONG" else entry_price * 1.1
    print(f"Calculated SL Price: {sl_price}")
    
    # Place Stop Loss
    print("Placing Stop Loss order...")
    sl_res = await client.place_order(
        symbol=symbol,
        side=close_side,
        position_side=side,
        order_type="STOP_MARKET",
        quantity=size,
        stop_price=sl_price
    )
    print("SL Result:", sl_res)
    
    # Place Take Profits
    tps = tp_manager.calculate_tps(entry_price, sl_price, size, side)
    for i, tp in enumerate(tps):
        print(f"Placing TP{i+1} at {tp['price']} for size {tp['qty']}...")
        tp_res = await client.place_order(
            symbol=symbol,
            side=close_side,
            position_side=side,
            order_type="TAKE_PROFIT_MARKET",
            quantity=tp["qty"],
            stop_price=tp["price"]
        )
        print(f"TP{i+1} Result:", tp_res)
        
    print("Rescue operations completed successfully!")
    await client.close()

if __name__ == "__main__":
    asyncio.run(rescue())
