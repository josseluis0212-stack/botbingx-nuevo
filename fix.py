import re, time

with open('app/core/engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

idx = content.find('                        # Evaluate Trailing and Breakeven')
idx2 = content.find('    async def _check_btc_volatility(self):')

if idx != -1 and idx2 != -1:
    new_block = """                        # Evaluate Trailing and Breakeven
                        await self._evaluate_trailing_and_breakeven(symbol, trade, mark_price, pos_amt)

                        # Smartly verify and restore protections to ensure positions are never left unprotected
                        await self.executor.verify_and_restore_protection(symbol, trade)

                    elif trade.get("entry_order_id") and not trade.get("filled"):
                        # REST-based fill detection: WS may have missed the fill event
                        pos = await self.executor.verify_position_exists(symbol, trade["side"])
                        if pos:
                            from app.logger import logger
                            logger.info(f"[REST FILL] Detected missing fill for {symbol} via REST fallback.")
                            trade["filled"] = True
                            await self._place_tp_sl_for_symbol(symbol, trade)
                        else:
                            from app.logger import logger
                            from app.config import Config
                            order_age = time.time() - trade.get("timestamp", time.time())
                            if order_age > Config.ENTRY_ORDER_MAX_AGE:
                                logger.info(f"[{symbol}] Pending entry order {trade['entry_order_id']} expired. Cancelling.")
                                await self.client._request(
                                    "DELETE", "/openApi/swap/v2/trade/order",
                                    params={"symbol": symbol.upper(), "orderId": trade["entry_order_id"]},
                                    signed=True
                                )
                                del self.trade_state[symbol]
                                continue

            # Update State
            await self._save_state()

        except Exception as e:
            from app.logger import logger
            logger.error(f"[{symbol}] Error in reconcile loop: {e}")

    async def _evaluate_trailing_and_breakeven(self, symbol, trade, mark_price, pos_amt):
        from app.logger import logger
        target_dist = trade.get("target_distance", 0)
        entry_price = trade.get("entry_price", 0)
        side = trade.get("side")

        if target_dist > 0:
            if side == "LONG":
                progress = (mark_price - entry_price) / target_dist
            else:
                progress = (entry_price - mark_price) / target_dist
        else:
            progress = 0.0

        if progress >= 0.70 and not trade.get("trailing_active"):
            logger.info(f"[TRAILING ACTIVATE] {symbol} progress reached {progress:.2%} (>= 70%). Cancelling TP and activating trailing stop.")
            tp_id = trade.get("tp1_order_id")
            tp_cancelled = True
            if tp_id:
                cancel_res = await self.client._request(
                    "DELETE", "/openApi/swap/v2/trade/order",
                    params={"symbol": symbol.upper(), "orderId": tp_id},
                    signed=True
                )
                if cancel_res.get("success") or cancel_res.get("code") in [100418, 100438]:
                    logger.info(f"[TRAILING ACTIVATE] TP order {tp_id} cancelled.")
                else:
                    logger.warning(f"[TRAILING ACTIVATE] TP cancel failed: {cancel_res.get('msg')}")
                    tp_cancelled = False

            if tp_cancelled:
                if side == "LONG":
                    floor_sl = entry_price + 0.50 * target_dist
                    trailing_sl = mark_price - 0.20 * target_dist
                    target_sl = max(floor_sl, trailing_sl)
                else:
                    floor_sl = entry_price - 0.50 * target_dist
                    trailing_sl = mark_price + 0.20 * target_dist
                    target_sl = min(floor_sl, trailing_sl)

                new_sl_id = await self.executor.update_sl(symbol, side, trade.get("sl_order_id"), target_sl, pos_amt)
                if new_sl_id:
                    trade["trailing_active"] = True
                    trade["highest_price"] = mark_price
                    trade["sl_order_id"] = new_sl_id
                    trade["sl_price"] = target_sl
                    logger.info(f"[TRAILING ACTIVATE] Trailing active. SL updated successfully.")
        
        elif trade.get("trailing_active"):
            highest_price = trade.get("highest_price", mark_price)
            if side == "LONG":
                if mark_price > highest_price:
                    trade["highest_price"] = mark_price
                    highest_price = mark_price
                trailing_sl = highest_price - 0.20 * target_dist
                floor_sl = entry_price + 0.50 * target_dist
                target_sl = max(trailing_sl, floor_sl)
                
                if target_sl > trade.get("sl_price", 0):
                    new_sl_id = await self.executor.update_sl(symbol, side, trade.get("sl_order_id"), target_sl, pos_amt)
                    if new_sl_id:
                        trade["sl_order_id"] = new_sl_id
                        trade["sl_price"] = target_sl
            else:
                if mark_price < highest_price:
                    trade["highest_price"] = mark_price
                    highest_price = mark_price
                trailing_sl = highest_price + 0.20 * target_dist
                floor_sl = entry_price - 0.50 * target_dist
                target_sl = min(trailing_sl, floor_sl)
                
                if target_sl < trade.get("sl_price", 0):
                    new_sl_id = await self.executor.update_sl(symbol, side, trade.get("sl_order_id"), target_sl, pos_amt)
                    if new_sl_id:
                        trade["sl_order_id"] = new_sl_id
                        trade["sl_price"] = target_sl

        elif progress >= 0.40 and not trade.get("breakeven_hit"):
            lock_in_profit = 0.20 * target_dist
            new_sl = entry_price + lock_in_profit if side == "LONG" else entry_price - lock_in_profit
            logger.info(f"[BREAKEVEN] {symbol} progress reached {progress:.2%} (>= 40%). Moving SL to {new_sl:.6f}.")
            new_sl_id = await self.executor.update_sl(symbol, side, trade.get("sl_order_id"), new_sl, pos_amt)
            if new_sl_id:
                trade["sl_order_id"] = new_sl_id
                trade["sl_price"] = new_sl
                trade["breakeven_hit"] = True

    import asyncio
    async def _fast_trailing_loop(self):
        \"\"\"
        Runs every 3 seconds. Queries get_ticker for active trades to catch fast wicks
        and activate trailing stop instantly.
        \"\"\"
        from app.logger import logger
        import asyncio
        await asyncio.sleep(5)
        while self.running:
            try:
                active_trades = [(sym, t) for sym, t in self.trade_state.items() if t.get("filled")]
                for symbol, trade in active_trades:
                    ticker = await self.client.get_ticker(symbol)
                    if ticker:
                        mark_price = float(ticker.get("lastPrice") or 0.0)
                        if mark_price > 0:
                            pos_amt = trade.get("remaining_size", trade.get("total_size", 0))
                            await self._evaluate_trailing_and_breakeven(symbol, trade, mark_price, pos_amt)
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"[FAST TRAILING] Error: {e}")
                await asyncio.sleep(3)

"""
    content_new = content[:idx] + new_block + content[idx2:]
    with open('app/core/engine.py', 'w', encoding='utf-8') as f:
        f.write(content_new)
    print("FIXED")
else:
    print("NOT FOUND")
