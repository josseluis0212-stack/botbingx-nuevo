import asyncio
import sys

# Adjust path to import from app
sys.path.append(".")

from app.exchange.bingx_client import AsyncBingXClient
from app.logger import logger

async def check_limits():
    client = AsyncBingXClient()
    
    # 1. Fetch top 50 volume symbols
    top_symbols = await client.get_top_volume_symbols(50)
    if not top_symbols:
        logger.error("Could not fetch top volume symbols.")
        return
        
    logger.info(f"Fetched top 50 symbols. Querying contract details...")
    
    # 2. Fetch all contract details
    res = await client._request('GET', '/openApi/swap/v2/quote/contracts', signed=False)
    if not res or 'data' not in res:
        logger.error("Could not fetch contract details.")
        return
        
    # Map symbols
    contract_map = {c['symbol']: c for c in res['data']}
    
    logger.info("=" * 70)
    logger.info(f"{'SYMBOL':<15} | {'MinQty':<10} | {'MinUSDT':<10} | {'Est Size ($8)':<12} | {'Est Value ($8)':<14}")
    logger.info("=" * 70)
    
    under_limits = 0
    
    for sym in top_symbols:
        sym_upper = sym.upper()
        if sym_upper not in contract_map:
            logger.warning(f"Symbol {sym_upper} not found in contracts list.")
            continue
            
        contract = contract_map[sym_upper]
        min_qty = float(contract.get('tradeMinQuantity', 0))
        min_usdt = float(contract.get('tradeMinUSDT', 0))
        
        # Let's estimate a standard trade with 2% SL distance
        # Entry price
        entry_price = float(contract.get('tradeMinQuantity', 0))  # just placeholder, let's look up actual ticker price if possible, or use standard
        
        logger.info(f"{sym_upper:<15} | {min_qty:<10.6f} | {min_usdt:<10.2f} USDT")
        
        if min_usdt > 8.0:
            logger.error(f"WARNING: Symbol {sym_upper} requires a minimum order value of {min_usdt} USDT, which is higher than our $8 risk!")
            under_limits += 1
            
    logger.info("=" * 70)
    if under_limits == 0:
        logger.info("ALL TOP 50 SYMBOLS ARE 100% COMPATIBLE WITH $8 RISK!")
    else:
        logger.warning(f"Found {under_limits} symbols with min USDT limit > $8.")

if __name__ == "__main__":
    asyncio.run(check_limits())
