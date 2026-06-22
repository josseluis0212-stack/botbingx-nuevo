import json
import time
import os

trades_path = r"c:\Users\Usuario\Documents\botbingxx\storage\trades.json"
runtime_path = r"c:\Users\Usuario\Documents\botbingxx\storage\runtime_state.json"

try:
    with open(trades_path, "r") as f:
        trades = json.load(f)
except Exception as e:
    trades = []
    print("Error reading trades:", e)

try:
    with open(runtime_path, "r") as f:
        runtime = json.load(f)
        open_trades = runtime.get("trade_state", {})
except Exception as e:
    open_trades = {}
    print("Error reading runtime_state:", e)

now = time.time()
past_24h = now - 24 * 3600

trades_24h = [t for t in trades if t.get("exit_time", 0) >= past_24h]

wins = 0
losses = 0
total_pnl = 0.0

print("--- TRADE LOG 24H ---")
for t in trades_24h:
    pnl = t.get("pnl", 0.0)
    total_pnl += pnl
    if pnl > 0:
        wins += 1
    elif pnl < 0:
        losses += 1
    print(f"{t.get('symbol')} | {t.get('side')} | PnL: {pnl:.4f} USDT | Reason: {t.get('reason')}")

print("\n--- STATS 24H ---")
print(f"Total Cerradas 24h: {len(trades_24h)}")
print(f"Ganadas: {wins}")
print(f"Perdidas: {losses}")
print(f"Win Rate: {(wins/len(trades_24h)*100 if trades_24h else 0):.1f}%")
print(f"PNL Realizado 24h: {total_pnl:.4f} USDT")

print("\n--- ABIERTAS ACTUALMENTE ---")
print(f"Total Abiertas: {len(open_trades)}")
for sym, t in open_trades.items():
    print(f" - {sym} ({t.get('side')}): Entry {t.get('entry_price')} | Size: {t.get('total_size')}")
