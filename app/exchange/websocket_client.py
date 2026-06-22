import asyncio
import time
import json
import websockets
import gzip
from app.config import Config
from app.logger import logger
from app.exchange.bingx_client import AsyncBingXClient

SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "BNB-USDT", "DOGE-USDT", "ADA-USDT", "LINK-USDT"]
TF_MAP = {"5m": "kline_5m", "15m": "kline_15m", "1m": "kline_1m"}

class BingXWebSocket:
    """
    Production-grade WebSocket client for BingX.
    Handles market data (klines) and private order fills.
    Features: auto-reconnect, exponential backoff, ping/pong, gzip decompression.
    """
    def __init__(self, message_callback, fill_callback=None, mark_price_callback=None):
        self.ws_url = Config.WS_URL
        self.message_callback = message_callback
        self.fill_callback = fill_callback
        self.mark_price_callback = mark_price_callback
        self.client = AsyncBingXClient()
        self.ws = None
        self._ping_task = None
        self.running = False
        self._reconnect_delay = 2
        self._subscribed = False
        # FIX Bug#4: Track active markPrice subs so we can re-subscribe after WS reconnect
        self._active_mark_price_subs: set = set()

    def _ws_open(self, ws=None):
        """Version-safe check if WebSocket connection is open. Works with websockets v10 and v11+."""
        conn = ws or self.ws
        if conn is None:
            return False
        # websockets v11+: use close_code (None means still open)
        if hasattr(conn, 'close_code'):
            return conn.close_code is None
        # websockets v10 and below: use .closed boolean
        if hasattr(conn, 'closed'):
            return not conn.closed
        # fallback: assume open
        return True

    async def _get_listen_key(self):
        try:
            res = await self.client._request("POST", "/openApi/user/auth/userDataStream", signed=True)
            if res.get("success") and res.get("data"):
                return res["data"].get("listenKey")
        except Exception as e:
            logger.error(f"Failed to get listen key: {e}")
        return None

    async def subscribe_mark_price(self, symbol: str):
        self._active_mark_price_subs.add(symbol)  # Always register even if WS not ready yet
        if self._ws_open():
            sub_msg = {
                "id": f"sub_mark_{symbol}",
                "reqType": "sub",
                "dataType": f"{symbol}@markPrice"
            }
            await self.ws.send(json.dumps(sub_msg))
            logger.info(f"Subscribed to Mark Price stream for {symbol}")

    async def unsubscribe_mark_price(self, symbol: str):
        self._active_mark_price_subs.discard(symbol)  # Remove from tracking
        if self._ws_open():
            unsub_msg = {
                "id": f"unsub_mark_{symbol}",
                "reqType": "unsub",
                "dataType": f"{symbol}@markPrice"
            }
            await self.ws.send(json.dumps(unsub_msg))
            logger.info(f"Unsubscribed from Mark Price stream for {symbol}")

    async def _subscribe_market_data(self, ws):
        tf_key = TF_MAP.get(Config.TIMEFRAME, "kline_5m")
        for i, symbol in enumerate(SYMBOLS):
            sub_msg = {
                "id": f"sub_kline_{i}",
                "reqType": "sub",
                "dataType": f"{symbol}@{tf_key}"
            }
            await ws.send(json.dumps(sub_msg))
            await asyncio.sleep(0.1)
        logger.info(f"Subscribed to {len(SYMBOLS)} symbols @ {Config.TIMEFRAME}")

    async def _subscribe_private_orders(self, ws, listen_key):
        if listen_key:
            sub_msg = {
                "id": "sub_orders",
                "reqType": "sub",
                "dataType": f"@listenKey"
            }
            await ws.send(json.dumps(sub_msg))
            logger.info("Subscribed to private order fill channel.")

    async def connect(self):
        self.running = True
        while self.running:
            try:
                listen_key = await self._get_listen_key()
                url = f"{self.ws_url}?listenKey={listen_key}" if listen_key else self.ws_url

                async with websockets.connect(
                    url,
                    ping_interval=None,
                    close_timeout=5,
                    max_size=10 * 1024 * 1024
                ) as ws:
                    self.ws = ws
                    self._reconnect_delay = 2  # Reset backoff on successful connect
                    logger.info(f"WebSocket connected: {url[:50]}...")

                    await self._subscribe_market_data(ws)
                    if listen_key:
                        await self._subscribe_private_orders(ws, listen_key)

                    self._ping_task = asyncio.create_task(self._keep_alive(ws))

                    # FIX Bug#4: Re-subscribe to all markPrice channels after reconnect
                    if self._active_mark_price_subs:
                        logger.info(f"[WS RECONNECT] Re-subscribing to {len(self._active_mark_price_subs)} markPrice channels...")
                        for sym in list(self._active_mark_price_subs):
                            resub_msg = {
                                "id": f"resub_mark_{sym}",
                                "reqType": "sub",
                                "dataType": f"{sym}@markPrice"
                            }
                            await ws.send(json.dumps(resub_msg))
                            await asyncio.sleep(0.05)
                        logger.info(f"[WS RECONNECT] ✅ All markPrice channels restored.")

                    async for message in ws:
                        if not self.running:
                            break
                        await self._handle_raw_message(message)

            except websockets.exceptions.ConnectionClosedOK:
                logger.warning("WebSocket closed cleanly. Reconnecting...")
            except websockets.exceptions.ConnectionClosedError as e:
                logger.error(f"WebSocket connection error: {e}. Reconnecting in {self._reconnect_delay}s...")
            except Exception as e:
                logger.error(f"WebSocket unexpected error: {e}. Reconnecting in {self._reconnect_delay}s...")

            if self.running:
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)  # Exponential backoff cap 60s

    async def _handle_raw_message(self, message):
        try:
            if isinstance(message, bytes):
                try:
                    message = gzip.decompress(message).decode('utf-8')
                except Exception:
                    message = message.decode('utf-8')

            if message in ("Ping", "ping"):
                if self._ws_open():
                    await self.ws.send("Pong")
                return

            data = json.loads(message)

            if data.get("ping"):
                if self._ws_open():
                    await self.ws.send(json.dumps({"pong": data["ping"]}))
                return

            # Detect order fill events (private channel)
            if data.get("e") in ("ORDER_TRADE_UPDATE", "executionReport") and self.fill_callback:
                await self.fill_callback(data)
                return

            # Route Mark Price updates
            if "markPrice" in data.get("dataType", "") and self.mark_price_callback:
                await self.mark_price_callback(data)
                return

            # Route to market data callback
            await self.message_callback(data)

        except json.JSONDecodeError:
            pass  # Ignore non-JSON messages
        except Exception as e:
            logger.error(f"Error handling WS message: {e}")

    async def _keep_alive(self, ws):
        while self.running:
            try:
                if self._ws_open(ws):
                    await ws.send(json.dumps({"ping": int(time.time() * 1000)}))
                await asyncio.sleep(20)
            except Exception:
                break

    async def stop(self):
        self.running = False
        if self._ping_task:
            self._ping_task.cancel()
        if self._ws_open():
            await self.ws.close()
        logger.info("WebSocket stopped.")