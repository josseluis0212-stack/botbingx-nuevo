# Application Constants
import os
from .config import Config

STORAGE_PATH = Config.STORAGE_DIR
TRADES_FILE = os.path.join(STORAGE_PATH, "trades.json")
POSITIONS_FILE = os.path.join(STORAGE_PATH, "positions.json")
RUNTIME_STATE_FILE = os.path.join(STORAGE_PATH, "runtime_state.json")
BOT_LOG_FILE = os.path.join(STORAGE_PATH, "bot.log")
ERRORS_LOG_FILE = os.path.join(STORAGE_PATH, "errors.log")
PNL_OFFSET_FILE = os.path.join(STORAGE_PATH, "pnl_offset.json")
BTC_BLOCK_FILE = os.path.join(STORAGE_PATH, "btc_block.json")

LOOKBACK_PERIOD = 15
MAX_BUFFER_SIZE = 500
RECONCILIATION_INTERVAL = 30