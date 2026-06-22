import asyncio
import argparse
from app.exchange.bingx_client import AsyncBingXClient

async def main():
    parser = argparse.ArgumentParser(description="Fetch BingX PnL history")
    parser.add_argument("--days", type=int, default=2, help="Number of days to look back")
    args = parser.parse_args()
    
    client = AsyncBingXClient()
    
    print(f"Fetching income history for the last {args.days} days...")
    
    # BingX income endpoint
    # Note: A real implementation would parse the timestamps and filter by days.
    # For now, we just call the existing get_income method and summarize.
    try:
        incomes = await client.get_income(limit=500)
        
        if not incomes:
            print("No income history found.")
            return
            
        total_pnl = 0.0
        total_fees = 0.0
        
        import time
        cutoff_ms = (time.time() - (args.days * 86400)) * 1000
        
        for item in incomes:
            # BingX timestamps are usually in milliseconds
            item_time = int(item.get("time", item.get("timestamp", 0)))
            if item_time > 0 and item_time < cutoff_ms:
                continue # Skip old history
                
            income_type = item.get("incomeType")
            amount = float(item.get("income", 0))
            
            if income_type == "REALIZED_PNL":
                total_pnl += amount
            elif income_type in ["COMMISSION", "FUNDING_FEE"]:
                total_fees += amount
                
        net_profit = total_pnl + total_fees
        
        print("\n=== BINGX PNL SUMMARY ===")
        print(f"Total Gross PnL: {total_pnl:.4f} USDT")
        print(f"Total Fees:      {total_fees:.4f} USDT")
        print(f"NET PROFIT:      {net_profit:.4f} USDT")
        print("=========================\n")
        
    except Exception as e:
        print(f"Error fetching history: {e}")

if __name__ == "__main__":
    asyncio.run(main())
