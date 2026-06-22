import asyncio
from typing import Optional
from app.exchange.bingx_client import AsyncBingXClient
from app.logger import logger
from app.config import Config

class OrderExecutionEngine:
    """
    Motor oficial de ejecución de órdenes.
    - Utiliza órdenes LIMIT avanzadas cercanas al precio para entrada.
    - Implementa backoff exponencial (3s, 5s, 10s, 15s) en fallos de red/API.
    - Verifica estados reales del exchange.
    """

    def __init__(self, client: AsyncBingXClient):
        self.client = client
        self.backoff_sequence = [3, 5, 10, 15]

    async def _execute_with_backoff(self, coro_func, *args, **kwargs) -> dict:
        """Wrapper to execute an async function with the required exponential backoff."""
        for attempt, wait_time in enumerate(self.backoff_sequence):
            try:
                res = await coro_func(*args, **kwargs)
                if res and res.get("success"):
                    return res
                else:
                    # Fail fast if market blew past our SL
                    if res.get("code") in [110411, 110412]:
                        logger.error(f"[EXEC ENGINE] Fatal API Error: {res.get('msg')} | Market blew past trigger. Failing fast.")
                        return res
                    logger.warning(f"[EXEC ENGINE] API Error on attempt {attempt+1}: {res.get('msg')} | Retrying in {wait_time}s")
            except Exception as e:
                logger.error(f"[EXEC ENGINE] Exception on attempt {attempt+1}: {e} | Retrying in {wait_time}s")
            
            await asyncio.sleep(wait_time)
            
        logger.error("[EXEC ENGINE] Max retries exhausted. Operation failed.")
        return {}

    async def place_entry_limit(self, symbol: str, side: str, size: float, price: float) -> Optional[str]:
        """
        Places a LIMIT order as close to current price as possible.
        """
        pos_side = "LONG" if side == "LONG" else "SHORT"
        order_side = "BUY" if side == "LONG" else "SELL"

        # Setup leverage dynamically just in case
        await self.client.set_margin_type(symbol, "ISOLATED")
        await self.client.set_leverage(symbol, "LONG", Config.LEVERAGE)
        await self.client.set_leverage(symbol, "SHORT", Config.LEVERAGE)

        logger.info(f"[EXEC ENTRY] Placing LIMIT {order_side}/{pos_side} {size:.6f} @ {price:.4f} on {symbol}")
        
        async def _call_api():
            return await self.client.place_order(
                symbol=symbol,
                side=order_side,
                position_side=pos_side,
                order_type="LIMIT",
                quantity=size,
                price=price,
                post_only=False, # Standard limit to get filled
                reduce_only=False
            )

        res = await self._execute_with_backoff(_call_api)
        
        if res and res.get("data"):
            order_data = res["data"].get("order", res["data"])
            order_id = str(order_data.get("orderId", ""))
            logger.info(f"[EXEC ENTRY] LIMIT Order placed OK. ID={order_id}")
            return order_id
            
        logger.error(f"[EXEC ENTRY] Aborting entry for {symbol} after backoff failures.")
        return None

    async def place_stop_loss(self, symbol: str, side: str, size: float, sl_price: float) -> Optional[str]:
        pos_side = "LONG" if side == "LONG" else "SHORT"
        close_side = "SELL" if side == "LONG" else "BUY"

        async def _call():
            return await self.client.place_order(
                symbol=symbol, side=close_side, position_side=pos_side,
                order_type="STOP_MARKET", quantity=size, stop_price=sl_price, reduce_only=True
            )

        res = await self._execute_with_backoff(_call)
        if res and res.get("data"):
            return str(res["data"].get("order", res["data"]).get("orderId", ""))
        return None

    async def place_take_profit(self, symbol: str, side: str, size: float, tp_price: float) -> Optional[str]:
        pos_side = "LONG" if side == "LONG" else "SHORT"
        close_side = "SELL" if side == "LONG" else "BUY"

        async def _call():
            return await self.client.place_order(
                symbol=symbol, side=close_side, position_side=pos_side,
                order_type="TAKE_PROFIT_MARKET", quantity=size, stop_price=tp_price, reduce_only=True
            )

        res = await self._execute_with_backoff(_call)
        if res and res.get("data"):
            return str(res["data"].get("order", res["data"]).get("orderId", ""))
        return None

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        async def _call():
            return await self.client._request(
                "DELETE", "/openApi/swap/v2/trade/order",
                params={"symbol": symbol.upper(), "orderId": order_id},
                signed=True
            )
        res = await self._execute_with_backoff(_call)
        if res and str(res.get("code", "")) == "0":
            logger.info(f"[EXECUTION] Successfully cancelled order {order_id} for {symbol}")
            return True
        logger.error(f"[EXECUTION] Failed to cancel order {order_id} for {symbol}. Response: {res}")
        return False

    async def close_position_market(self, symbol: str, side: str, size: float):
        """Emergency market close."""
        pos_side = "LONG" if side == "LONG" else "SHORT"
        close_side = "SELL" if side == "LONG" else "BUY"
        
        await self.client.cancel_all_orders(symbol)

        async def _call():
            return await self.client.place_order(
                symbol=symbol, side=close_side, position_side=pos_side,
                order_type="MARKET", quantity=size, reduce_only=True
            )
            
        await self._execute_with_backoff(_call)
