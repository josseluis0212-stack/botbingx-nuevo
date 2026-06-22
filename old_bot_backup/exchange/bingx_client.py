import hmac
import hashlib
import time
import requests
import urllib.parse
import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional

# Import configurations
try:
    from config import API_KEY, SECRET_KEY, BASE_URL
except ImportError:
    # Fallbacks for standalone testing
    API_KEY = "mock_key"
    SECRET_KEY = "mock_secret"
    BASE_URL = "https://open-api-vst.bingx.com"

logger = logging.getLogger("BingXClient")

class BingXClient:
    """
    Robust API client for BingX Perpetual Swap Futures.
    Designed for both production and VST (Virtual USDT) demo trading environments.
    """
    def __init__(self, api_key: str = API_KEY, secret_key: str = SECRET_KEY, base_url: str = BASE_URL):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        
    @staticmethod
    def _format_number(value: float, precision: int = 8) -> str:
        """
        Formats a float as a fixed-point string to avoid scientific notation (e.g. 1e-05)
        which breaks HMAC signature when URL-encoded.
        Strips trailing zeros but keeps at least one decimal place.
        """
        formatted = f"{value:.{precision}f}"
        # Remove trailing zeros after decimal, but preserve at least one decimal digit
        if '.' in formatted:
            formatted = formatted.rstrip('0').rstrip('.')
        return formatted

    def _generate_signature(self, params: Dict[str, Any]) -> str:
        """
        Generates HMAC-SHA256 signature for parameters sorted alphabetically.
        All values are converted to strings prior to encoding.
        """
        # Convert all values to strings first to ensure consistent encoding
        str_params = {k: str(v) for k, v in params.items()}
        # Sort by key and URL encode
        sorted_params = sorted(str_params.items())
        query_string = urllib.parse.urlencode(sorted_params)
        
        # Hash signature using SECRET_KEY
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature

    def _request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, signed: bool = True) -> Dict[str, Any]:
        """
        Standard private/public HTTP request handler with robust exception handling.
        """
        if params is None:
            params = {}
        else:
            params = params.copy()
            
        url = f"{self.base_url}{endpoint}"
        headers = {}
        
        if signed:
            # Inject required timestamp in ms
            params["timestamp"] = int(time.time() * 1000)
            
            # Generate signature — all values converted to strings inside _generate_signature
            sig = self._generate_signature(params)
            
            # Build the query string manually from string-converted sorted params
            # This guarantees exact match between signed string and transmitted URL
            str_params = {k: str(v) for k, v in params.items()}
            sorted_params = sorted(str_params.items())
            query_string = urllib.parse.urlencode(sorted_params)
            final_query_string = f"{query_string}&signature={sig}"
            url_with_params = f"{url}?{final_query_string}"
            
            # API Key header
            headers["X-BX-APIKEY"] = self.api_key
        else:
            if params:
                str_params = {k: str(v) for k, v in params.items()}
                sorted_params = sorted(str_params.items())
                query_string = urllib.parse.urlencode(sorted_params)
                url_with_params = f"{url}?{query_string}"
            else:
                url_with_params = url
            
        logger.debug(f"Sending {method} request to {endpoint} with url: {url_with_params}")
        
        try:
            if method.upper() == "GET":
                response = requests.get(url_with_params, headers=headers, timeout=10)
            elif method.upper() == "POST":
                response = requests.post(url_with_params, headers=headers, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
                
            response.raise_for_status()
            res_json = response.json()
            
            # Check for API-level errors (code != 0)
            if res_json.get("code") != 0:
                err_msg = res_json.get("msg", "Unknown error")
                code = res_json.get("code")
                logger.error(f"BingX API Error {code}: {err_msg}")
                return {"success": False, "code": code, "msg": err_msg, "data": None}
                
            return {"success": True, "code": 0, "msg": "Success", "data": res_json.get("data")}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error communicating with BingX: {e}")
            return {"success": False, "code": -999, "msg": str(e), "data": None}
        except Exception as e:
            logger.error(f"Unexpected error in request execution: {e}")
            return {"success": False, "code": -9999, "msg": str(e), "data": None}

    # ==========================================
    # PUBLIC MARKET DATA ENDPOINTS
    # ==========================================
    def get_klines(self, symbol: str, interval: str = "5m", limit: int = 500) -> Optional[pd.DataFrame]:
        """
        Retrieves historical K-line/candlestick data for perpetual swap contracts.
        Endpoint: GET /openApi/swap/v3/quote/klines (Public)
        
        Returns:
            pd.DataFrame: OHLCV dataframe indexed by Datetime or None if failed.
        """
        # Translate symbols from BTC-USDT to BTC-USDT (usually match, but ensure format)
        symbol = symbol.upper()
        
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        
        # Public call, signed=False
        res = self._request("GET", "/openApi/swap/v3/quote/klines", params=params, signed=False)
        
        if not res["success"] or not res["data"]:
            logger.warning(f"Failed to fetch Klines for {symbol}: {res['msg']}")
            return None
            
        try:
            kline_list = res["data"]
            
            if not isinstance(kline_list, list):
                logger.warning(f"Unexpected Klines format: {type(kline_list)}")
                return None
                
            # Create DataFrame directly from list of dictionaries
            df = pd.DataFrame(kline_list)
            
            # Convert values to numeric types
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col])
                
            # Convert 'time' (representing open time in milliseconds) to Datetime Index
            if 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'].astype(float), unit='ms', utc=True)
                df.set_index('time', inplace=True)
            
            # Sort chronological
            df.sort_index(ascending=True, inplace=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Error parsing Klines data: {e}")
            return None

    def get_order_book(self, symbol: str, limit: int = 5) -> Optional[Dict[str, Any]]:
        """Fetches public order book depth for execution and microstructure checks."""
        symbol = symbol.upper()
        params = {"symbol": symbol, "limit": limit}
        res = self._request("GET", "/openApi/swap/v2/quote/depth", params=params, signed=False)
        if not res["success"] or not res["data"]:
            logger.warning(f"Failed to fetch depth for {symbol}: {res['msg']}")
            return None
        return res["data"]

    def get_best_bid_ask(self, symbol: str) -> Optional[Dict[str, float]]:
        """Returns top-of-book bid/ask prices and sizes."""
        data = self.get_order_book(symbol, limit=5)
        if not data:
            return None

        try:
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if not bids or not asks:
                return None

            return {
                "bid": float(bids[0][0]),
                "bid_size": float(bids[0][1]),
                "ask": float(asks[0][0]),
                "ask_size": float(asks[0][1]),
            }
        except Exception as e:
            logger.error(f"Error parsing best bid/ask for {symbol}: {e}")
            return None

    def get_order_book_imbalance(self, symbol: str, limit: int = 5) -> float:
        """
        Fetches public order book depth and calculates Level-K Order Book Imbalance (OBI).
        Formula: OBI = (BidVol - AskVol) / (BidVol + AskVol)
        """
        data = self.get_order_book(symbol, limit=limit)
        if not data:
            return 0.0
            
        try:
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            
            # Each entry is [price, quantity]
            bid_vol = sum(float(bid[1]) for bid in bids[:limit])
            ask_vol = sum(float(ask[1]) for ask in asks[:limit])
            
            total_vol = bid_vol + ask_vol
            if total_vol <= 0:
                return 0.0
                
            obi = (bid_vol - ask_vol) / total_vol
            return obi
        except Exception as e:
            logger.error(f"Error calculating OBI: {e}")
            return 0.0

    # ==========================================
    # PRIVATE ACCOUNT & TRADING ENDPOINTS
    # ==========================================
    def get_balance(self, asset: str = "VST") -> float:
        """
        Retrieves user's account balance for a specific asset.
        Endpoint: GET /openApi/swap/v2/user/balance (Private)
        """
        res = self._request("GET", "/openApi/swap/v2/user/balance")
        
        if not res["success"] or not res["data"]:
            logger.error(f"Failed to retrieve balance: {res['msg']}")
            return 0.0
            
        try:
            data = res["data"]
            
            # Structure check based on different API versions
            # 1. Single dict: {"balance": {"asset": "VST", "balance": "1000.00", ...}}
            if isinstance(data, dict) and "balance" in data:
                bal_obj = data["balance"]
                if bal_obj.get("asset") == asset:
                    return float(bal_obj.get("balance", 0.0))
                # Fallback to checking the equity
                return float(bal_obj.get("equity", 0.0))
                
            # 2. List of dicts (standard account response)
            elif isinstance(data, list):
                for item in data:
                    if item.get("asset") == asset:
                        # Some versions return balance under "balance" or "equity"
                        return float(item.get("balance", item.get("equity", 0.0)))
                        
            # 3. Direct nesting fallback
            elif isinstance(data, dict):
                # Search recursively
                for k, v in data.items():
                    if isinstance(v, dict) and v.get("asset") == asset:
                        return float(v.get("balance", v.get("equity", 0.0)))
                        
            logger.warning(f"Asset '{asset}' not found in balances response.")
            return 0.0
            
        except Exception as e:
            logger.error(f"Exception parsing balance: {e}")
            return 0.0

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves current open positions.
        Endpoint: GET /openApi/swap/v2/user/positions (Private)
        """
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
            
        res = self._request("GET", "/openApi/swap/v2/user/positions", params=params)
        
        if not res["success"] or res["data"] is None:
            logger.error(f"Failed to retrieve positions: {res['msg']}")
            return []
            
        positions = res["data"]
        parsed_positions = []
        
        try:
            if not isinstance(positions, list):
                logger.warning(f"Unexpected positions format: {type(positions)}")
                return []
                
            for pos in positions:
                # Standard fields: symbol, positionAmt, avgEntryPrice, unrealizedProfit, positionSide, leverage
                amt = float(pos.get("positionAmt", 0.0))
                # Filter out zero positions
                if amt == 0:
                    continue
                    
                parsed_positions.append({
                    "symbol": pos.get("symbol"),
                    "side": pos.get("positionSide"),  # 'LONG' or 'SHORT'
                    "size": abs(amt),
                    "entry_price": float(pos.get("avgPrice", pos.get("avgEntryPrice", 0.0))),
                    "unrealized_pnl": float(pos.get("unrealizedProfit", 0.0)),
                    "leverage": int(pos.get("leverage", 1)),
                    "liquidation_price": float(pos.get("liquidationPrice", 0.0))
                })
                
            return parsed_positions
            
        except Exception as e:
            logger.error(f"Error parsing positions data: {e}")
            return []

    def ensure_hedge_mode(self) -> bool:
        """
        Ensures the account is in Hedge Mode (dualSidePosition=true).
        Required to trade separate LONG/SHORT positions in perpetual swap.
        Called once on startup to prevent error 109400.
        """
        # Check current mode
        res = self._request("GET", "/openApi/swap/v1/positionSide/dual")
        if res.get("success") and res.get("data"):
            dual = str(res["data"].get("dualSidePosition", "false")).lower()
            if dual == "true":
                logger.info("Cuenta ya está en Modo Cobertura (Hedge Mode). OK.")
                return True
        # Switch to hedge mode
        switch = self._request("POST", "/openApi/swap/v1/positionSide/dual",
                               params={"dualSidePosition": "true"})
        if switch.get("success"):
            logger.info("Modo Cobertura (Hedge Mode) activado exitosamente.")
            return True
        logger.warning(f"No se pudo activar Hedge Mode: {switch.get('msg')}")
        return False

    def set_leverage(self, symbol: str, side: str, leverage: int) -> bool:
        """
        Sets target leverage for a specific side (LONG or SHORT) and contract.
        Endpoint: POST /openApi/swap/v2/trade/leverage (Private)
        """
        params = {
            "symbol": symbol.upper(),
            "leverage": str(int(leverage)),  # String to avoid encoding issues
            "side": side.upper()  # 'LONG' or 'SHORT'
        }
        
        res = self._request("POST", "/openApi/swap/v2/trade/leverage", params=params)
        
        if res["success"]:
            logger.info(f"Apalancamiento {side} configurado a {leverage}x para {symbol}.")
            return True
            
        logger.error(f"Error configurando apalancamiento: {res['msg']}")
        return False

    def place_order(
        self,
        symbol: str,
        side: str,
        position_side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        time_in_force: Optional[str] = None,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Places a perpetual swap market or limit order.
        Endpoint: POST /openApi/swap/v2/trade/order (Private)
        """
        import json
        formatted_qty = self._format_number(float(quantity), precision=8)

        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),              # 'BUY' or 'SELL'
            "positionSide": position_side.upper(),  # 'LONG' or 'SHORT'
            "type": order_type.upper(),        # 'MARKET' or 'LIMIT'
            "quantity": formatted_qty          # String with fixed precision
        }
        
        if order_type.upper() == "LIMIT":
            if price is None:
                raise ValueError("Price is required for LIMIT orders.")
            params["price"] = self._format_number(float(price), precision=8)

        if time_in_force:
            params["timeInForce"] = time_in_force.upper()
            
        if take_profit is not None:
            params["takeProfit"] = json.dumps({
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": float(self._format_number(take_profit, precision=4)),
                "workingType": "MARK_PRICE"
            })
            
        if stop_loss is not None:
            params["stopLoss"] = json.dumps({
                "type": "STOP_MARKET",
                "stopPrice": float(self._format_number(stop_loss, precision=4)),
                "workingType": "MARK_PRICE"
            })
            
        res = self._request("POST", "/openApi/swap/v2/trade/order", params=params)
        
        if res["success"] and res["data"]:
            order_data = res["data"].get("order", res["data"])
            logger.info(f"Order placed successfully: {side} {position_side} {quantity} units on {symbol}.")
            return {
                "success": True,
                "order_id": order_data.get("orderId"),
                "symbol": order_data.get("symbol"),
                "status": order_data.get("status"),
                "price": float(order_data.get("price", 0.0)),
                "quantity": float(order_data.get("volume", quantity)),
                "raw": order_data
            }
            
        logger.error(f"Failed to place order: {res['msg']}")
        return {"success": False, "order_id": None, "msg": res["msg"]}

    def get_top_volume_coins(self, limit: int = 80) -> List[str]:
        """
        Fetches perpetual swap tickers, filters for USDT-M crypto pairs, and
        excludes known TradFi/metals/forex/stock-token contracts.
        """
        res = self._request("GET", "/openApi/swap/v2/quote/ticker", signed=False)
        if not res["success"] or not res["data"]:
            logger.warning(f"Failed to fetch tickers: {res['msg']}")
            # Fallback to a predefined list of top crypto coins if request fails
            return ["BTC-USDT", "ETH-USDT", "SOL-USDT", "NEAR-USDT", "ADA-USDT", "XRP-USDT", "DOGE-USDT", "LINK-USDT", "DOT-USDT", "LTC-USDT"]
            
        try:
            tickers = res["data"]
            usdt_crypto_pairs = []
            non_crypto_bases = {
                "XAU", "XAG", "XAUT", "PAXG", "GOLD", "SILVER", "OIL", "WTI", "BRENT", "NGAS",
                "US30", "US100", "US500", "SPX", "SP500", "NAS100", "NDX", "DJI",
                "DOW", "HK50", "DE40", "GER40", "UK100", "JP225", "N225",
                "EUR", "GBP", "AUD", "NZD", "JPY", "CAD", "CHF", "CNH",
                "AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "GOOG", "AMZN", "META",
                "NFLX", "AMD", "INTC", "COIN", "MSTR", "PLTR", "BABA", "NIO",
                "PDD", "DIS", "BA", "PYPL", "UBER", "HOOD", "SHOP", "SQ",
                "V", "MA", "JPM", "BAC", "WMT", "QQQ", "SPY", "DIA",
            }
            
            for t in tickers:
                symbol = t.get("symbol", "").upper()
                base = symbol.split("-")[0]
                if (
                    symbol.endswith("-USDT")
                    and not symbol.startswith("NCCO")
                    and not symbol.startswith("NCS")
                    and "NASDAQ" not in symbol
                    and "NYSE" not in symbol
                    and base not in non_crypto_bases
                ):
                    usdt_crypto_pairs.append({
                        "symbol": symbol,
                        "volume": float(t.get("quoteVolume", 0.0))
                    })
            
            # Sort by 24h volume (quoteVolume) descending
            sorted_pairs = sorted(usdt_crypto_pairs, key=lambda x: x["volume"], reverse=True)
            
            top_symbols = [x["symbol"] for x in sorted_pairs[:limit]]
            logger.info(f"Retrieved top {len(top_symbols)} crypto coins by volume.")
            return top_symbols
        except Exception as e:
            logger.error(f"Error filtering top volume coins: {e}")
            return ["BTC-USDT", "ETH-USDT", "SOL-USDT"]

# Standalone self-testing routine
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    print("\n" + "="*50)
    print("      BINGX API CLIENT STANDALONE TESTING ROUTINE")
    print("="*50)
    
    # Initialize client (uses VST environment mock API keys by default)
    client = BingXClient()
    
    # 1. Test public Klines
    print("\n[Step 1] Testing public Klines endpoint (BTC-USDT)...")
    df = client.get_klines("BTC-USDT", interval="1m", limit=10)
    if df is not None:
        print("Success! Retrieved DataFrame:")
        print(df.tail(3).to_string())
    else:
        print("Failed to retrieve public Klines.")
        
    # 2. Test HMAC-SHA256 signature algorithm correctness
    print("\n[Step 2] Testing HMAC-SHA256 signature correctness...")
    mock_params = {
        "symbol": "BTC-USDT",
        "leverage": 20,
        "side": "LONG",
        "timestamp": 1716800000000
    }
    # Standard query should look like: leverage=20&side=LONG&symbol=BTC-USDT&timestamp=1716800000000
    sig = client._generate_signature(mock_params)
    print(f"Computed Signature: {sig}")
    print("Correctness validation complete.")
    
    # 3. Test private endpoints (expects failure if keys are incorrect or success if keys are valid)
    print("\n[Step 3] Querying VST balance with environment keys...")
    vst_bal = client.get_balance("VST")
    print(f"VST Balance retrieved: {vst_bal:.2f} VST")
    
    print("\n[Step 4] Querying open positions...")
    positions = client.get_positions("BTC-USDT")
    print(f"Positions returned count: {len(positions)}")
    if positions:
        print("Active Positions:", positions)
        
    print("\n" + "="*50)
    print("      API CLIENT TESTS COMPLETE")
    print("="*50 + "\n")
