import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, '.')
from app.exchange.bingx_client import AsyncBingXClient

async def main():
    client = AsyncBingXClient()
    
    print("Fetching complete user income history from BingX (limit=1000)...")
    # Fetch up to 1000 items
    income_items = await client.get_income(limit=1000)
    
    if not income_items:
        print("No income items fetched from BingX.")
        await client.close()
        return
        
    print(f"Fetched {len(income_items)} income items total.")
    
    # Convert target UTC datetimes to millisecond timestamps
    start_dt = datetime(2026, 6, 2, 19, 17, 56, tzinfo=timezone.utc)
    end_dt = datetime(2026, 6, 4, 19, 17, 56, tzinfo=timezone.utc)
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    
    print(f"Filtering items between {start_dt} ({start_ts}) and {end_dt} ({end_ts})...")
    
    # Let's count incomeType occurrences inside the window
    types_in_window = {}
    filtered_items = []
    for item in income_items:
        t = int(item["time"])
        if start_ts <= t <= end_ts:
            filtered_items.append(item)
            inc_type = item.get("incomeType", "UNKNOWN")
            types_in_window[inc_type] = types_in_window.get(inc_type, 0) + 1
            
    print(f"Found {len(filtered_items)} items in the 48-hour window.")
    print("Income type distribution in window:", types_in_window)
    
    gross_profit = 0.0
    gross_loss = 0.0
    trading_fees = 0.0
    funding_fees = 0.0
    other_income = 0.0
    win_trades = 0
    loss_trades = 0
    
    symbol_stats = {}
    
    for item in filtered_items:
        symbol = item.get("symbol", "UNKNOWN")
        inc_type = item.get("incomeType")
        val = float(item.get("income", 0.0))
        
        if symbol not in symbol_stats:
            symbol_stats[symbol] = {
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "trading_fee": 0.0,
                "funding_fee": 0.0,
                "other": 0.0,
                "win_trades": 0,
                "loss_trades": 0
            }
            
        if inc_type == "REALIZED_PNL":
            if val > 0:
                gross_profit += val
                win_trades += 1
                symbol_stats[symbol]["gross_profit"] += val
                symbol_stats[symbol]["win_trades"] += 1
            elif val < 0:
                gross_loss += val
                loss_trades += 1
                symbol_stats[symbol]["gross_loss"] += val
                symbol_stats[symbol]["loss_trades"] += 1
        elif inc_type == "TRADING_FEE":
            trading_fees += val
            symbol_stats[symbol]["trading_fee"] += val
        elif inc_type == "FUNDING_FEE":
            funding_fees += val
            symbol_stats[symbol]["funding_fee"] += val
        else:
            other_income += val
            symbol_stats[symbol]["other"] += val
            
    # Performance Calculations
    total_trades = win_trades + loss_trades
    win_rate = (win_trades / total_trades * 100.0) if total_trades > 0 else 0.0
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss != 0 else float('inf')
    mean_win = (gross_profit / win_trades) if win_trades > 0 else 0.0
    mean_loss = (gross_loss / loss_trades) if loss_trades > 0 else 0.0
    
    # Formula requested: Gross Profit + Gross Loss + Fees
    net_pnl = gross_profit + gross_loss + trading_fees
    
    print("\n================== 48H PERFORMANCE SUMMARY ==================")
    print(f"Total Gross Profit:  {gross_profit:.8f}")
    print(f"Total Gross Loss:    {gross_loss:.8f}")
    print(f"Total Trading Fees:  {trading_fees:.8f}")
    print(f"Total Net PNL:       {net_pnl:.8f}")
    print(f"Total Win Trades:    {win_trades}")
    print(f"Total Loss Trades:   {loss_trades}")
    print(f"Win Rate:            {win_rate:.2f}%")
    print(f"Profit Factor:       {profit_factor:.4f}" if profit_factor != float('inf') else "Profit Factor:       N/A (No loss)")
    print(f"Mean Win:            {mean_win:.8f}")
    print(f"Mean Loss:           {mean_loss:.8f}")
    if funding_fees != 0:
        print(f"Total Funding Fees:  {funding_fees:.8f} (Not in Net PNL formula)")
    if other_income != 0:
        print(f"Total Other Income:  {other_income:.8f} (Not in Net PNL formula)")
    print("=============================================================\n")
    
    # Print grouping by symbol
    print("================ PERFORMANCE BY SYMBOL ================")
    # Sort symbols by Net PNL (Gross Profit + Gross Loss + Trading Fee)
    sorted_symbols = []
    for sym, stats in symbol_stats.items():
        sym_net = stats["gross_profit"] + stats["gross_loss"] + stats["trading_fee"]
        sorted_symbols.append((sym, sym_net, stats))
        
    sorted_symbols.sort(key=lambda x: x[1], reverse=True)
    
    print(f"{'Symbol':<22} | {'Gross Profit':<12} | {'Gross Loss':<12} | {'Fees':<10} | {'Net PNL':<12} | {'W/L':<5} | {'Win%':<6}")
    print("-" * 90)
    for sym, sym_net, stats in sorted_symbols:
        sym_win_trades = stats["win_trades"]
        sym_loss_trades = stats["loss_trades"]
        sym_total = sym_win_trades + sym_loss_trades
        sym_win_rate = (sym_win_trades / sym_total * 100.0) if sym_total > 0 else 0.0
        
        print(f"{sym:<22} | {stats['gross_profit']:12.6f} | {stats['gross_loss']:12.6f} | {stats['trading_fee']:10.6f} | {sym_net:12.6f} | {sym_win_trades}/{sym_loss_trades} | {sym_win_rate:5.1f}%")
        
    print("=======================================================")
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
