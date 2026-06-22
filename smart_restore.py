    async def verify_and_restore_protection(self, symbol: str, trade: dict):
        """
        Smartly checks active orders on BingX and ONLY places missing SL/TPs.
        Avoids the cancel-everything loop.
        """
        open_orders = await self.client.get_open_orders(symbol)
        
        has_sl = False
        tp_count = 0
        
        if open_orders:
            for order in open_orders:
                o_type = order.get("type", order.get("orderType", ""))
                if o_type == "STOP_MARKET":
                    has_sl = True
                elif o_type == "TAKE_PROFIT_MARKET":
                    tp_count += 1
                    
        # Verify sizes and prices
        pos = await self.verify_position_exists(symbol, trade["side"])
        if not pos:
            return # Position closed
            
        real_size = abs(float(pos.get("positionAmt", 0)))
        entry_price = float(pos.get("avgPrice", trade.get("entry_price", 0)))
        side = trade["side"]
        
        pos_side = "LONG" if side == "LONG" else "SHORT"
        close_side = "SELL" if side == "LONG" else "BUY"
        
        # Determine SL price
        sl_price = trade.get("sl_price")
        if not sl_price:
            sl_price = entry_price * 0.98 if side == "LONG" else entry_price * 1.02
            
        # Place SL if missing
        if not has_sl and trade.get("sl_order_id") != "BREACHED":
            logger.info(f"[SMART RESTORE] {symbol} SL missing. Placing once...")
            sl_res = await self.client.place_order(
                symbol=symbol, side=close_side, position_side=pos_side,
                order_type="STOP_MARKET", quantity=real_size, stop_price=sl_price
            )
            if sl_res.get("success") and sl_res.get("data"):
                trade["sl_order_id"] = str(sl_res["data"].get("order", sl_res["data"]).get("orderId", ""))
            else:
                code = sl_res.get("code")
                if code in [110411, 110412]:
                    logger.error(f"[SMART RESTORE] {symbol} SL breached. Marking BREACHED.")
                    trade["sl_order_id"] = "BREACHED"
                else:
                    logger.error(f"[SMART RESTORE] SL failed: {sl_res.get('msg')}")
                    
        # Place TPs if missing (if no TPs exist, assume we need to place all 3)
        if tp_count == 0 and not trade.get("tp1_hit"):
            logger.info(f"[SMART RESTORE] {symbol} TPs missing. Placing TPs...")
            tps = self.tp_manager.calculate_tps(entry_price, sl_price, real_size, side)
            
            for i, tp in enumerate(tps):
                tp_res = await self.client.place_order(
                    symbol=symbol, side=close_side, position_side=pos_side,
                    order_type="TAKE_PROFIT_MARKET", quantity=tp["qty"], stop_price=tp["price"]
                )
                if tp_res.get("success") and tp_res.get("data"):
                    order_id = str(tp_res["data"].get("order", tp_res["data"]).get("orderId", ""))
                    if i == 0: trade["tp1_order_id"] = order_id
                    elif i == 1: trade["tp2_order_id"] = order_id
                    elif i == 2: trade["tp3_order_id"] = order_id
                else:
                    logger.error(f"[SMART RESTORE] TP{i+1} failed: {tp_res.get('msg')}")
