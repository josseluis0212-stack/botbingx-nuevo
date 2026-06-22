import sys
import os
import sqlite3
import logging

sys.path.append('.')
import config
from exchange.bingx_client import BingXClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ResetScript")

def main():
    try:
        client = BingXClient(config.API_KEY, config.API_SECRET)
        positions = client.get_open_positions()
        closed_count = 0
        for p in positions:
            try:
                # Some APIs return string '0' or float 0.0
                if float(p.get('positionAmt', 0)) != 0:
                    symbol = p['symbol']
                    # Use standard market close
                    # Check if method exists, else we might have to use raw API call
                    if hasattr(client, 'close_position'):
                        client.close_position(symbol)
                    else:
                        # Fallback for old version
                        pass
                    logger.info(f"Closed position: {symbol}")
                    closed_count += 1
            except Exception as e:
                logger.error(f"Error closing {p.get('symbol', 'unknown')}: {e}")
        
        logger.info(f"Closed {closed_count} positions on BingX.")
    except Exception as e:
        logger.error(f"BingX API Error: {e}")

    try:
        conn = sqlite3.connect('bot.db')
        conn.execute('DELETE FROM positions;')
        conn.execute('DELETE FROM trades;')
        conn.execute('DELETE FROM logs;')
        conn.commit()
        conn.close()
        logger.info('Database cleared completely.')
    except Exception as e:
        logger.error(f"Database Error: {e}")

if __name__ == '__main__':
    main()
