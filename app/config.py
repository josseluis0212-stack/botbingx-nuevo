import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_KEY = os.getenv("BINGX_API_KEY", "")
    SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "")
    DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
    TIMEFRAME = os.getenv("TIMEFRAME", "15m")
    POSITION_MARGIN = float(os.getenv("POSITION_MARGIN", "12.0"))
    MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "5"))
    LEVERAGE = int(os.getenv("LEVERAGE", "10"))
    ENTRY_ORDER_MAX_AGE = int(os.getenv("ENTRY_ORDER_MAX_AGE", "1800"))
    MIN_VOLUME_24H = float(os.getenv("MIN_VOLUME_24H", "500000"))
    EARLY_EXIT_VOL_MULT = float(os.getenv("EARLY_EXIT_VOL_MULT", "1.8"))
    EARLY_EXIT_LOOKBACK_MINUTES = int(os.getenv("EARLY_EXIT_LOOKBACK_MINUTES", "20"))
    SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "15"))
    USE_TELEGRAM = os.getenv("USE_TELEGRAM", "false").lower() == "true"
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Hardcoded reset timestamp to ignore old ephemeral history
    PNL_START_TIME = 1781923540310
    
    # BTC Volatility Block Parameters
    BTC_VOLATILITY_BLOCK_DURATION = int(os.getenv("BTC_VOLATILITY_BLOCK_DURATION", "7200"))  # 2 hours in seconds
    BTC_VOL_CUMUL_BODY_PCT = float(os.getenv("BTC_VOL_CUMUL_BODY_PCT", "1.5"))
    BTC_VOL_CUMUL_RANGE_PCT = float(os.getenv("BTC_VOL_CUMUL_RANGE_PCT", "1.5"))
    
    # Cooldown
    COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "60"))
    
    # Base URLs
    REST_URL = "https://open-api-vst.bingx.com" if DEMO_MODE else "https://open-api.bingx.com"
    WS_URL = "wss://open-api-ws.bingx.com/market"
    
    # Paths
    STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")

os.makedirs(Config.STORAGE_DIR, exist_ok=True)
