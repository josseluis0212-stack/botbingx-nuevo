"""
Real-Time Strategy Debugger — Full Pipeline Test
Steps 1-5: Signal scan, order placement, account check, forced order, verify
"""
import asyncio
import sys
import json

sys.path.insert(0, '.')

from app.exchange.bingx_client import AsyncBingXClient
from app.data.candle_buffer import CandleBuffer
from app.strategy.liquidity_sweep import detect_sweep
from app.strategy.signal_score import calculate_score
from app.strategy.confirmations import filter_confirmations
from app.strategy.volatility_filter import is_volatile_enough
from app.strategy.market_structure import validate_structure
from app.exchange.order_executor import OrderExecutor

SYMBOLS = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT',
           'BNB-USDT', 'DOGE-USDT', 'ADA-USDT', 'LINK-USDT']

SEP = "=" * 70


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Full pipeline scan on all 8 symbols
# ─────────────────────────────────────────────────────────────────────────────
async def step1_scan(client):
    print(f"\n{SEP}")
    print("STEP 1: Full pipeline scan — all 8 symbols")
    print(SEP)

    tradeable = []   # list of dicts for symbols ready to trade

    for symbol in SYMBOLS:
        buf = CandleBuffer()
        klines = await client.get_klines(symbol, '5m', 50)
        if not klines:
            print(f"  {symbol}: ❌ NO KLINES returned from API")
            continue

        klines_sorted = sorted(klines, key=lambda x: x['time'])
        for i, k in enumerate(klines_sorted):
            candle = dict(k)
            candle['closed'] = (i < len(klines_sorted) - 1)
            buf.add_candle(candle)

        buf_len = len(buf)
        recent = buf.get_recent(17)
        if recent is None:
            print(f"  {symbol}: ❌ Buffer too small (has {buf_len}, need 17)")
            continue

        volatile = is_volatile_enough(recent)
        sweep = detect_sweep(recent)
        sig = sweep.get('signal', 'NONE')

        if sig != 'NONE':
            score = calculate_score(recent, sweep)
            conf = filter_confirmations(recent, sweep)
            struct = validate_structure(recent, sig)
            entry = sweep.get('entry_price', 0)
            sl = sweep.get('sl_price', 0)
            print(f"  {symbol}: SIGNAL={sig}  score={score}  conf={conf}  "
                  f"struct={struct}  entry={entry:.6f}  sl={sl:.6f}")

            # Detailed breakdown
            sweep_c = recent[-2]
            confirm_c = recent[-1]
            body = abs(confirm_c['close'] - confirm_c['open'])
            wick = confirm_c['high'] - confirm_c['low']
            body_ratio = (body / wick * 100) if wick > 0 else 0
            print(f"    confirm: open={confirm_c['open']:.6f} close={confirm_c['close']:.6f} "
                  f"body={body_ratio:.1f}%  vol_confirm={confirm_c.get('volume', 0):.2f}  "
                  f"vol_sweep={sweep_c.get('volume', 0):.2f}")

            if score >= 40 and conf and struct:
                print(f"  ✅ >>> WOULD TRADE {symbol} {sig}! <<<")
                tradeable.append({
                    'symbol': symbol,
                    'side': sig,
                    'entry': entry,
                    'sl': sl,
                    'score': score,
                })
            else:
                reasons = []
                if score < 40:
                    reasons.append(f"score={score}<40")
                if not conf:
                    reasons.append("conf=False")
                if not struct:
                    reasons.append("struct=False")
                print(f"  ⚠️  Signal found but blocked: {', '.join(reasons)}")
        else:
            print(f"  {symbol}: no signal  (volatile={volatile}, buf={buf_len})")

    return tradeable


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Place entry order for any tradeable signal
# ─────────────────────────────────────────────────────────────────────────────
async def step2_place_signal_orders(tradeable):
    print(f"\n{SEP}")
    print("STEP 2: Place LIMIT entry orders for qualifying signals")
    print(SEP)

    if not tradeable:
        print("  No qualifying signals from Step 1 — skipping Step 2.")
        return []

    executor = OrderExecutor()
    placed = []

    for t in tradeable:
        symbol = t['symbol']
        side = t['side']
        entry = t['entry']
        # Use a quantity of 1 contract (minimum) — adjust if needed
        qty = 1.0

        print(f"  Placing {side} LIMIT @ {entry:.6f} on {symbol} qty={qty}")
        order_id = await executor.place_entry(symbol, side, qty, entry)
        if order_id:
            print(f"  ✅ Order placed! ID={order_id}")
            placed.append({'symbol': symbol, 'side': side,
                           'price': entry, 'order_id': order_id})
        else:
            print(f"  ❌ Failed to place order for {symbol} {side}")

    return placed


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: Check account balance and open orders
# ─────────────────────────────────────────────────────────────────────────────
async def step3_check_account(client):
    print(f"\n{SEP}")
    print("STEP 3: Account balance and open orders check")
    print(SEP)

    balance = await client.get_balance()
    print(f"  Balance (equity): {balance}")

    for sym in SYMBOLS:
        orders = await client.get_open_orders(sym)
        if orders:
            print(f"  {sym} open orders ({len(orders)}):")
            for o in orders:
                print(f"    orderId={o.get('orderId')}  side={o.get('side')}/"
                      f"{o.get('positionSide')}  type={o.get('type')}  "
                      f"price={o.get('price')}  qty={o.get('origQty')}  "
                      f"status={o.get('status')}")
        else:
            pass  # quiet on empty


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: Force-place ONE order on BTC-USDT 0.5% below current price
# ─────────────────────────────────────────────────────────────────────────────
async def step4_force_order(client):
    print(f"\n{SEP}")
    print("STEP 4: Force-place BTC-USDT LONG 0.5% below current price")
    print(SEP)

    symbol = 'BTC-USDT'
    klines = await client.get_klines(symbol, '5m', 2)
    if not klines:
        print(f"  ❌ Could not get klines for {symbol}")
        return None

    current_price = klines[-1]['close']
    limit_price = round(current_price * 0.995, 2)   # 0.5% below market
    qty = 0.001                                       # smallest BTC lot

    print(f"  Current BTC price : {current_price:.2f}")
    print(f"  Limit order price : {limit_price:.2f}  (−0.5%)")
    print(f"  Quantity          : {qty} BTC")

    executor = OrderExecutor()
    order_id = await executor.place_entry(symbol, 'LONG', qty, limit_price)

    if order_id:
        print(f"  ✅ Forced order placed! Order ID = {order_id}")
    else:
        print("  ❌ Forced order FAILED — see logs above for API error details")

    return order_id


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: Verify the forced order appears on BingX
# ─────────────────────────────────────────────────────────────────────────────
async def step5_verify_order(client, order_id):
    print(f"\n{SEP}")
    print("STEP 5: Verify forced order appears on BingX")
    print(SEP)

    if not order_id:
        print("  No order ID to verify (Step 4 failed).")
        return

    await asyncio.sleep(1)   # tiny pause to let the exchange register it

    orders = await client.get_open_orders('BTC-USDT')
    if not orders:
        print("  ❌ No open orders found for BTC-USDT on exchange!")
        return

    found = False
    for o in orders:
        if str(o.get('orderId')) == str(order_id):
            found = True
            print(f"  ✅ Order CONFIRMED on BingX!")
            print(f"     orderId    : {o.get('orderId')}")
            print(f"     side       : {o.get('side')}/{o.get('positionSide')}")
            print(f"     type       : {o.get('type')}")
            print(f"     price      : {o.get('price')}")
            print(f"     qty        : {o.get('origQty')}")
            print(f"     status     : {o.get('status')}")
            print(f"     createTime : {o.get('time')}")
            break

    if not found:
        print(f"  ⚠️  Order {order_id} not found among {len(orders)} open orders.")
        print("     All open orders on BTC-USDT:")
        for o in orders:
            print(f"       {o.get('orderId')} | price={o.get('price')} "
                  f"qty={o.get('origQty')} status={o.get('status')}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    print(SEP)
    print("  REAL-TIME STRATEGY DEBUGGER — BingX Pipeline Full Run")
    print(SEP)

    client = AsyncBingXClient()

    # Step 1
    tradeable = await step1_scan(client)

    # Step 2
    placed = await step2_place_signal_orders(tradeable)

    # Step 3
    await step3_check_account(client)

    # Step 4 (always force-place a test order)
    forced_id = await step4_force_order(client)

    # Step 5
    await step5_verify_order(client, forced_id)

    print(f"\n{SEP}")
    print("  DEBUGGER COMPLETE")
    print(SEP)

    # Summary
    print("\n📋 SUMMARY")
    print(f"  Symbols scanned      : {len(SYMBOLS)}")
    print(f"  Qualifying signals   : {len(tradeable)}")
    if tradeable:
        for t in tradeable:
            print(f"    → {t['symbol']} {t['side']} score={t['score']} entry={t['entry']:.6f}")
    print(f"  Orders placed (sig)  : {len(placed)}")
    print(f"  Forced order ID      : {forced_id or 'FAILED'}")


if __name__ == "__main__":
    asyncio.run(main())
