import hmac
import hashlib
import time
import urllib.parse
import aiohttp
import json
import re
import asyncio
from app.config import Config
from app.logger import logger

class AsyncBingXClient:
    def __init__(self):
        self.api_key = Config.API_KEY
        self.secret_key = Config.SECRET_KEY
        self.base_url = Config.REST_URL
        self._session = None
        self._contract_precisions = {}
        
    async def get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
        
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
        
    @staticmethod
    def _format_number(value: float, precision: int = 8) -> str:
        formatted = f"{value:.{precision}f}"
        if '.' in formatted:
            formatted = formatted.rstrip('0').rstrip('.')
        return formatted

    def _generate_signature(self, params: dict) -> str:
        str_params = {k: str(v) for k, v in params.items()}
        sorted_params = sorted(str_params.items())
        query_string = urllib.parse.urlencode(sorted_params)
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    async def _request(self, method: str, endpoint: str, params: dict = None, signed: bool = True, max_retries: int = 3):
        url = f"{self.base_url}{endpoint}"
        session = await self.get_session()
        
        for attempt in range(max_retries):
            if params is None:
                current_params = {}
            else:
                current_params = params.copy()
                
            headers = {}
            if signed:
                current_params["timestamp"] = int(time.time() * 1000)
                sig = self._generate_signature(current_params)
                str_params = {k: str(v) for k, v in current_params.items()}
                sorted_params = sorted(str_params.items())
                query_string = urllib.parse.urlencode(sorted_params)
                final_query_string = f"{query_string}&signature={sig}"
                url_with_params = f"{url}?{final_query_string}"
                headers["X-BX-APIKEY"] = self.api_key
            else:
                if current_params:
                    str_params = {k: str(v) for k, v in current_params.items()}
                    sorted_params = sorted(str_params.items())
                    query_string = urllib.parse.urlencode(sorted_params)
                    url_with_params = f"{url}?{query_string}"
                else:
                    url_with_params = url

            try:
                if method.upper() == "GET":
                    async with session.get(url_with_params, headers=headers, timeout=10) as resp:
                        res_json = await resp.json()
                elif method.upper() == "POST":
                    async with session.post(url_with_params, headers=headers, timeout=10) as resp:
                        res_json = await resp.json()
                elif method.upper() == "DELETE":
                    async with session.delete(url_with_params, headers=headers, timeout=10) as resp:
                        res_json = await resp.json()
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                if "listenKey" in res_json and "code" not in res_json:
                    return {"success": True, "data": res_json, "msg": "Success", "code": 0}
                
                if res_json.get("code") != 0:
                    err_msg = res_json.get("msg", "Unknown error")
                    code = res_json.get("code")
                    logger.error(f"BingX API Error on {url}: {err_msg} | Code: {code} | Raw: {res_json}")
                    
                    # Handle IP Ban (109429)
                    if code == 109429:
                        match = re.search(r'retry after time:\s*(\d+)', err_msg)
                        if match:
                            retry_time_ms = int(match.group(1))
                            wait_sec = (retry_time_ms / 1000.0) - time.time()
                            if wait_sec > 0:
                                logger.error(f"[PENALTY BOX] API banned by BingX. Sleeping for {wait_sec:.1f} seconds to let the ban expire...")
                                await asyncio.sleep(wait_sec + 2)
                                continue

                    # Don't retry on obvious validation errors like invalid parameters or missing orders
                    if code in [100400, 100440, 101211, 101215, 100418, 100438]: 
                        return {"success": False, "data": None, "msg": err_msg, "code": code}
                    # For other codes (like rate limits or server errors), continue loop to retry
                else:
                    return {"success": True, "data": res_json.get("data"), "msg": "Success", "code": 0}
                    
            except Exception as e:
                logger.error(f"API Request Exception (Attempt {attempt+1}/{max_retries}): {e}")
                
            # If we reach here, there was an exception or a retryable API error
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))  # exponential backoff
                
        return {"success": False, "data": None, "msg": "Max retries exceeded"}

    async def get_klines(self, symbol: str, interval: str = "5m", limit: int = 100) -> list:
        """
        Fetch OHLCV klines from BingX REST API.

        BingX v3 klines endpoint returns a list of dicts.  The exact field names
        can vary between API versions, so we accept multiple aliases:
          open  → "open" | "o"
          high  → "high" | "h"
          low   → "low"  | "l"
          close → "close"| "c"
          volume→ "volume"| "v"
          time  → "time" | "t" | "T"  (open time, milliseconds)

        Returns a list of dicts with guaranteed float/int values:
          {"open": float, "high": float, "low": float, "close": float,
           "volume": float, "time": int}
        Returns [] on any error.
        """
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        res = await self._request("GET", "/openApi/swap/v3/quote/klines", params=params, signed=False)
        raw = res.get("data", [])
        if not raw or not isinstance(raw, list):
            return []

        parsed = []
        for k in raw:
            try:
                parsed.append({
                    "open":   float(k.get("open",   k.get("o",  0))),
                    "high":   float(k.get("high",   k.get("h",  0))),
                    "low":    float(k.get("low",    k.get("l",  0))),
                    "close":  float(k.get("close",  k.get("c",  0))),
                    "volume": float(k.get("volume", k.get("vol", k.get("v",  0)))),
                    "time":   int(k.get("time",     k.get("t",  k.get("T", 0)))),
                })
            except (TypeError, ValueError) as e:
                logger.warning(f"[get_klines] Skipping malformed kline entry: {k} | {e}")
                continue
        return parsed

    async def get_positions(self, symbol: str = None):
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        res = await self._request("GET", "/openApi/swap/v2/user/positions", params=params, signed=True)
        return res.get("data", [])

    async def get_ticker(self, symbol: str) -> dict:
        """Fetch ticker details (lastPrice, askPrice, bidPrice) for a symbol."""
        res = await self._request("GET", "/openApi/swap/v2/quote/ticker", {"symbol": symbol.upper()}, signed=False)
        if res.get("success") and res.get("data"):
            return res["data"]
        return {}

    async def set_leverage(self, symbol: str, side: str, leverage: int):
        params = {
            "symbol": symbol.upper(),
            "leverage": str(int(leverage)),
            "side": side.upper()
        }
        res = await self._request("POST", "/openApi/swap/v2/trade/leverage", params=params, signed=True)
        return res.get("success", False)

    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED"):
        params = {
            "symbol": symbol.upper(),
            "marginType": margin_type.upper()
        }
        res = await self._request("POST", "/openApi/swap/v2/trade/marginType", params=params, signed=True)
        return res.get("success", False)

    async def get_contract_precisions(self):
        if not self._contract_precisions:
            import aiohttp
            try:
                # Force real API for precision metadata since VST is incomplete for new altcoins
                async with aiohttp.ClientSession() as session:
                    async with session.get("https://open-api.bingx.com/openApi/swap/v2/quote/contracts") as response:
                        if response.status == 200:
                            res = await response.json()
                            if res and "data" in res:
                                for c in res["data"]:
                                    self._contract_precisions[c["symbol"]] = {
                                        "qty": c.get("quantityPrecision", 4),
                                        "price": c.get("pricePrecision", 2)
                                    }
            except Exception as e:
                from app.logger import logger
                logger.error(f"[PRECISION] Error fetching real precisions: {e}")
            
            # Fallback if empty
            if not self._contract_precisions:
                res = await self._request("GET", "/openApi/swap/v2/quote/contracts", signed=False)
                if res and "data" in res:
                    for c in res["data"]:
                        self._contract_precisions[c["symbol"]] = {
                            "qty": c.get("quantityPrecision", 4),
                            "price": c.get("pricePrecision", 2)
                        }
        return self._contract_precisions

    async def place_order(self, symbol: str, side: str, position_side: str, order_type: str, quantity: float, price: float = None, stop_price: float = None, post_only: bool = False, reduce_only: bool = False):
        await self.get_contract_precisions()
        prec = self._contract_precisions.get(symbol.upper(), {"qty": 4, "price": 2})

        formatted_qty = self._format_number(float(quantity), precision=prec["qty"])
        if not formatted_qty or float(formatted_qty) <= 0:
            logger.warning(f"[place_order] Formatted quantity is '{formatted_qty}' (raw={quantity}) for {symbol}. Skipping order placement to avoid API error.")
            return {"success": False, "msg": "Formatted quantity is 0.", "code": 109400}

        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "positionSide": position_side.upper(),
            "type": order_type.upper(),
            "quantity": formatted_qty
        }
        if price is not None:
            params["price"] = self._format_number(float(price), precision=prec["price"])
        if stop_price is not None:
            formatted_stop = self._format_number(float(stop_price), precision=prec["price"])
            if not formatted_stop or float(formatted_stop) <= 0:
                logger.warning(f"[place_order] Formatted stopPrice is '{formatted_stop}' (raw={stop_price}) for {symbol}. Skipping order placement to avoid API error.")
                return {"success": False, "msg": "Formatted stopPrice is 0.", "code": 109400}
            params["stopPrice"] = formatted_stop
            # By default, BingX uses Mark Price for triggers. Change to Last Price (CONTRACT_PRICE)
            # so that fast liquidity wicks correctly trigger our Stop Losses and Take Profits.
            params["workingType"] = "CONTRACT_PRICE"
            
        if order_type.upper() == "LIMIT":
            if price is None:
                return {"success": False, "msg": "LIMIT order requires price."}
            if post_only:
                params["timeInForce"] = "PostOnly"
        if reduce_only:
            params["reduceOnly"] = "true"
            
        res = await self._request("POST", "/openApi/swap/v2/trade/order", params=params, signed=True)
        return res

    # Duplicate definition removed to prevent collision. Class uses the filtered implementation below.

    async def cancel_all_orders(self, symbol: str):
        params = {"symbol": symbol.upper()}
        res = await self._request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", params=params, signed=True)
        
        # BingX allOpenOrders doesn't always clear trigger/stop orders, so we sweep manually
        open_orders = await self.get_open_orders(symbol)
        if open_orders:
            for order in open_orders:
                order_id = order.get("orderId")
                if order_id:
                    await self._request("DELETE", "/openApi/swap/v2/trade/order", params={"symbol": symbol.upper(), "orderId": order_id}, signed=True)
        return res.get("success", False)

    async def get_balance(self, asset: str = "VST") -> float:
        """Fetch account equity/balance for the given asset."""
        res = await self._request("GET", "/openApi/swap/v2/user/balance", signed=True)
        if not res.get("success") or not res.get("data"):
            logger.error(f"Failed to get balance: {res.get('msg')}")
            return 0.0
        try:
            data = res["data"]
            if isinstance(data, dict) and "balance" in data:
                bal_obj = data["balance"]
                return float(bal_obj.get("equity", bal_obj.get("balance", 0.0)))
            if isinstance(data, list):
                for item in data:
                    if item.get("asset") == asset:
                        return float(item.get("balance", item.get("equity", 0.0)))
            return 0.0
        except Exception as e:
            logger.error(f"Error parsing balance: {e}")
            return 0.0

    async def ensure_hedge_mode(self) -> bool:
        """Ensure account is in Hedge Mode (required for LONG+SHORT simultaneously)."""
        res = await self._request("GET", "/openApi/swap/v1/positionSide/dual", signed=True)
        if res.get("success") and res.get("data"):
            dual = str(res["data"].get("dualSidePosition", "false")).lower()
            if dual == "true":
                logger.info("Hedge Mode already active.")
                return True
        switch = await self._request("POST", "/openApi/swap/v1/positionSide/dual",
                                     params={"dualSidePosition": "true"}, signed=True)
        if switch.get("success"):
            logger.info("Hedge Mode activated.")
            return True
        logger.warning(f"Could not activate Hedge Mode: {switch.get('msg')}")
        return False

    async def get_open_orders(self, symbol: str) -> list:
        """Fetch all open orders for a symbol, strictly filtering by symbol (ignores dashes)."""
        params = {"symbol": symbol.upper()}
        res = await self._request("GET", "/openApi/swap/v2/trade/openOrders", params=params, signed=True)
        if res.get("success") and res.get("data"):
            orders = res["data"].get("orders", [])
            # Strictly filter by symbol to handle BingX API quirk returning all active orders
            return [o for o in orders if o.get("symbol", "").upper().replace("-", "") == symbol.upper().replace("-", "")]
        return []

    async def get_top_volume_symbols(self, limit: int = 80) -> list:
        """Fetch the top N USDT symbols by 24h volume."""
        res = await self._request("GET", "/openApi/swap/v2/quote/ticker", signed=False)
        if not res.get("success") or not res.get("data"):
            logger.error("Failed to fetch tickers for top volume calculation.")
            return []
        
        tickers = res.get("data")
        if not tickers:
            return []
            
        # Filter only USDT pairs and those with valid volume
        usdt_pairs = []
        for t in tickers:
            if t.get("symbol", "").endswith("-USDT"):
                usdt_pairs.append({
                    "symbol": t["symbol"],
                    "volume": float(t.get("volume", 0))
                })
        
        # Sort by volume descending
        usdt_pairs.sort(key=lambda x: x["volume"], reverse=True)
        
        # Return top N symbols
        top_symbols = [t["symbol"] for t in usdt_pairs[:limit]]
        logger.info(f"Fetched top {len(top_symbols)} volume symbols.")
        return top_symbols

    async def get_income(self, limit: int = 1000) -> list:
        """Fetch income history (Realized PNL, funding fees, commissions)."""
        # BingX v2 income endpoint
        params = {"limit": limit}
        res = await self._request("GET", "/openApi/swap/v2/user/income", params=params, signed=True)
        if res.get("success") and res.get("data"):
            return res["data"]
        return []

    async def get_listen_key(self) -> str:
        """Fetch the listen key for user data stream."""
        res = await self._request("POST", "/openApi/user/auth/userDataStream", signed=True)
        if res.get("success") and res.get("data"):
            return res["data"].get("listenKey", "")
        return ""