import os

# API Configurations for BingX VST (Demo Trading)
API_KEY = os.getenv("BINGX_API_KEY", "83SwzN3Rf9FjsfzswrACVH5fL4VSoLaxATw8EUVwbmQH0dmw3676Sv3Pch4mqTtDrMka97GqCKJQC4KjttcFPQ")
SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "7JkN8wZ9sj2Zt7VNGdk4ovCMPQ5jm9dIZXX324M7UlWcNFyn0amE4sOeJLRqh0sq8DL2xgYNLCfdNDJKJg")

# Trading Parameters
DEFAULT_LEVERAGE = int(os.getenv("BINGX_DEFAULT_LEVERAGE", "20"))
RISK_PER_TRADE = float(os.getenv("BINGX_RISK_PER_TRADE", "0.02"))  # 2% default risk
ACTIVE_SYMBOL = os.getenv("BINGX_ACTIVE_SYMBOL", "BTC-USDT")

# API Base URL
BASE_URL = os.getenv("BINGX_BASE_URL", "https://open-api-vst.bingx.com")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.db")
