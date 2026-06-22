import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import datetime
import os
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

st.set_page_config(
    page_title="Panel de Control — Scalper BingX VST",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.db')

# ── Background trader thread ──────────────────────────────────────────────────
import threading

def start_background_trader():
    for t in threading.enumerate():
        if t.name == "ExecutionTraderThread":
            return
    try:
        from execution.trader import ExecutionTrader
        trader = ExecutionTrader()
        t = threading.Thread(target=trader.start_loop, name="ExecutionTraderThread", daemon=True)
        t.start()
    except Exception as e:
        print(f"Failed to start background execution thread: {e}")

start_background_trader()

# ── DB Helpers ────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT,
        size REAL, entry_price REAL, leverage INTEGER, unrealized_pnl REAL, timestamp TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT,
        size REAL, entry_price REAL, exit_price REAL, leverage INTEGER,
        pnl REAL, timestamp TEXT, result TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, level TEXT, message TEXT)''')
    cursor.execute("SELECT COUNT(*) FROM bot_state")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO bot_state (key, value) VALUES ('running_state', '1')")
        cursor.execute("INSERT INTO bot_state (key, value) VALUES ('vst_balance', '100000.0')")
        cursor.execute("INSERT INTO bot_state (key, value) VALUES ('risk_per_trade', '1.5')")
        cursor.execute("INSERT INTO bot_state (key, value) VALUES ('leverage', '10')")
        cursor.execute("INSERT INTO bot_state (key, value) VALUES ('selected_symbol', 'BTC-USDT')")
        conn.commit()
    # Ensure sl/tp columns exist on positions table
    for col in ['sl', 'tp', 'initial_sl', 'initial_tp', 'peak_price',
                 'breakeven_active', 'trailing_active', 'take_profit_active']:
        try:
            cursor.execute(f"ALTER TABLE positions ADD COLUMN {col} REAL")
        except Exception:
            pass
            
    # Ensure exit_reason column exists on trades table
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN exit_reason TEXT")
    except Exception:
        pass
        
    conn.commit()
    conn.close()

def get_state(key):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_state WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def update_state(key, value):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_positions():
    conn = get_db()
    df = pd.read_sql_query("SELECT * FROM positions ORDER BY timestamp DESC", conn)
    conn.close()
    return df

def get_trades():
    conn = get_db()
    df = pd.read_sql_query("SELECT * FROM trades ORDER BY timestamp DESC", conn)
    conn.close()
    return df

def get_logs(limit=60):
    conn = get_db()
    df = pd.read_sql_query(f"SELECT * FROM logs ORDER BY id DESC LIMIT {limit}", conn)
    conn.close()
    return df

def log_message(level, message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO logs (timestamp, level, message) VALUES (?, ?, ?)",
                   (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), level, message))
    conn.commit()
    conn.close()

def close_position(pos_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM positions WHERE id = ?", (pos_id,))
    pos = cursor.fetchone()
    if pos:
        symbol = pos['symbol']
        side = pos['side']
        size = pos['size']
        entry_price = pos['entry_price']
        leverage = pos['leverage']
        unrealized_pnl = pos['unrealized_pnl']
        exit_price = (entry_price + unrealized_pnl / size) if side == 'LONG' else (entry_price - unrealized_pnl / size)
        result = 'WIN' if unrealized_pnl >= 0 else 'LOSS'
        cursor.execute('''INSERT INTO trades (symbol, side, size, entry_price, exit_price, leverage, pnl, timestamp, result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (symbol, side, size, entry_price, exit_price, leverage, unrealized_pnl,
             datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), result))
        cursor.execute("SELECT value FROM bot_state WHERE key = 'vst_balance'")
        new_bal = float(cursor.fetchone()[0]) + unrealized_pnl
        cursor.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES ('vst_balance', ?)", (str(new_bal),))
        cursor.execute("DELETE FROM positions WHERE id = ?", (pos['id'],))
        cursor.execute("INSERT INTO logs (timestamp, level, message) VALUES (?, ?, ?)",
                       (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'SUCCESS',
                        f"Cerrado {side} en {symbol} a ${exit_price:.4f}. PnL: {unrealized_pnl:+.2f} VST"))
        conn.commit()
    conn.close()

def open_manual_position(symbol, side, size, price, leverage):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,))
    if cursor.fetchone():
        log_message('WARNING', f"Ya existe una posicion abierta en {symbol}.")
        conn.close()
        return False
    cursor.execute('''INSERT INTO positions (symbol, side, size, entry_price, leverage, unrealized_pnl, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (symbol, side, size, price, leverage, 0.0, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    cursor.execute("INSERT INTO logs (timestamp, level, message) VALUES (?, ?, ?)",
                   (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'SUCCESS',
                    f"Orden manual {side} en {symbol}: {size:.4f} uds @ ${price:.4f} | {leverage}x"))
    conn.commit()
    conn.close()
    return True

# ── Chart Data ────────────────────────────────────────────────────────────────
def generate_chart_data(symbol, num_candles=150):
    seed_val = abs(hash(symbol)) % 10000
    np.random.seed(seed_val)
    prices_map = {'BTC': (63000.0, 180.0), 'ETH': (3100.0, 18.0), 'SOL': (152.0, 1.6),
                  'XRP': (0.52, 0.005), 'DOGE': (0.12, 0.002), 'BNB': (400.0, 4.0), 'ADA': (0.45, 0.004)}
    base, vol = 1.0, 0.01
    for k, (b, v_) in prices_map.items():
        if k in symbol.upper():
            base, vol = b, v_
            break

    prices = [base]
    for _ in range(num_candles - 1):
        prices.append(prices[-1] + np.random.normal(0.12, vol))
    timestamps = [datetime.datetime.now() - datetime.timedelta(minutes=5 * i) for i in range(num_candles)]
    timestamps.reverse()
    data = []
    for i, t in enumerate(timestamps):
        bp = prices[i]
        o = bp + np.random.normal(0, vol * 0.25)
        c = bp + np.random.normal(0, vol * 0.25)
        h = max(o, c) + abs(np.random.normal(0, vol * 0.35))
        l = min(o, c) - abs(np.random.normal(0, vol * 0.35))
        v = np.random.randint(50, 1500) if 'BTC' in symbol else np.random.randint(500, 15000)
        data.append({'time': t.strftime('%Y-%m-%d %H:%M'), 'open': o, 'high': h, 'low': l, 'close': c, 'volume': v})
    df = pd.DataFrame(data)
    df['rsi'] = 50 + np.random.normal(0, 10, len(df)).cumsum().clip(-30, 30)
    df['atr'] = (df['high'] - df['low']).rolling(14, min_periods=1).mean()
    return df

# ── Init ──────────────────────────────────────────────────────────────────────
init_db()
df_positions = get_positions()
df_trades = get_trades()
balance = float(get_state('vst_balance') or 100000)
is_running = get_state('running_state') == '1'
active_symbol = get_state('selected_symbol') or 'BTC-USDT'

# ── Derived Metrics ───────────────────────────────────────────────────────────
open_pnl = df_positions['unrealized_pnl'].sum() if not df_positions.empty else 0.0
total_trades = len(df_trades)
win_trades = len(df_trades[df_trades['result'] == 'WIN']) if total_trades > 0 else 0
loss_trades = total_trades - win_trades
win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
net_profit = df_trades['pnl'].sum() if not df_trades.empty else 0.0
avg_win = df_trades[df_trades['result'] == 'WIN']['pnl'].mean() if win_trades > 0 else 0.0
avg_loss = df_trades[df_trades['result'] == 'LOSS']['pnl'].mean() if loss_trades > 0 else 0.0
profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
max_drawdown = 0.0
if not df_trades.empty:
    cumulative = df_trades['pnl'].iloc[::-1].cumsum()
    rolling_max = cumulative.cummax()
    drawdown = cumulative - rolling_max
    max_drawdown = drawdown.min()
total_exposure = len(df_positions) * 200.0
open_positions_count = len(df_positions)
today = datetime.datetime.now().strftime('%Y-%m-%d')
trades_today = df_trades[df_trades['timestamp'].str.startswith(today, na=False)] if not df_trades.empty else pd.DataFrame()
pnl_today = trades_today['pnl'].sum() if not trades_today.empty else 0.0

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', sans-serif;
    background: radial-gradient(ellipse at 0% 0%, #0a0e2e 0%, #05070f 60%, #020205 100%);
    color: #f1f5f9 !important;
}
.block-container { padding-top: 1.5rem !important; padding-bottom: 2rem !important; max-width: 98% !important; }
h1,h2,h3,h4,h5,h6 { font-family:'Inter',sans-serif; font-weight:700!important; letter-spacing:-0.02em; color:#fff!important; }
[data-testid="stHeader"] { background:rgba(5,7,15,0.5)!important; backdrop-filter:blur(10px); border-bottom:1px solid rgba(255,255,255,0.04); }

/* ── Cards ── */
.kpi-card {
    background: linear-gradient(135deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0.01) 100%);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 18px;
    padding: 18px 20px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.45);
    transition: all 0.3s cubic-bezier(.4,0,.2,1);
    min-height: 110px;
}
.kpi-card:hover { transform:translateY(-3px); box-shadow:0 16px 48px rgba(99,102,241,0.18); border-color:rgba(99,102,241,0.3); }
.kpi-card.green { border-left:4px solid #10b981; }
.kpi-card.red { border-left:4px solid #ef4444; }
.kpi-card.blue { border-left:4px solid #6366f1; }
.kpi-card.amber { border-left:4px solid #f59e0b; }
.kpi-card.cyan { border-left:4px solid #06b6d4; }
.kpi-card.purple { border-left:4px solid #a855f7; }
.kpi-label { font-size:0.72rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.1em; margin-bottom:6px; }
.kpi-value { font-size:1.65rem; font-weight:800; letter-spacing:-0.03em; line-height:1.15; }
.kpi-sub { font-size:0.75rem; font-weight:500; color:#64748b; margin-top:5px; display:flex; align-items:center; gap:5px; }

/* ── Section Headers ── */
.section-hdr {
    font-size:0.85rem; font-weight:700; text-transform:uppercase; letter-spacing:0.1em;
    color:#e2e8f0; padding-bottom:10px; border-bottom:1px solid rgba(255,255,255,0.07);
    margin-bottom:16px; display:flex; align-items:center; gap:8px;
}

/* ── Positions Table ── */
.pos-row {
    display:grid; grid-template-columns:1.4fr 0.7fr 1fr 1fr 0.6fr 1fr 0.9fr 1fr 0.8fr;
    align-items:center; padding:10px 12px; border-radius:10px;
    background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05);
    margin-bottom:6px; font-size:0.83rem; transition:background 0.2s;
}
.pos-row:hover { background:rgba(99,102,241,0.07); }
.pos-hdr {
    display:grid; grid-template-columns:1.4fr 0.7fr 1fr 1fr 0.6fr 1fr 0.9fr 1fr 0.8fr;
    padding:6px 12px; font-size:0.72rem; font-weight:600; color:#475569;
    text-transform:uppercase; letter-spacing:0.08em; margin-bottom:4px;
}
.badge-long { color:#10b981; font-weight:700; background:rgba(16,185,129,0.1); padding:2px 8px; border-radius:6px; }
.badge-short { color:#ef4444; font-weight:700; background:rgba(239,68,68,0.1); padding:2px 8px; border-radius:6px; }
.mono { font-family:'JetBrains Mono','Courier New',monospace; font-size:0.82rem; }

/* ── LED ── */
.led-wrap { display:inline-flex; align-items:center; gap:10px; font-size:0.88rem; font-weight:600;
    background:rgba(255,255,255,0.04); padding:7px 16px; border-radius:30px; border:1px solid rgba(255,255,255,0.08); }
.led-g { width:9px; height:9px; background:#10b981; border-radius:50%;
    box-shadow:0 0 8px #10b981,0 0 16px #10b981; animation:pg 2s infinite; }
.led-r { width:9px; height:9px; background:#ef4444; border-radius:50%;
    box-shadow:0 0 8px #ef4444,0 0 16px #ef4444; animation:pr 2s infinite; }
@keyframes pg { 0%{transform:scale(.9);box-shadow:0 0 0 0 rgba(16,185,129,.7)} 70%{transform:scale(1.1);box-shadow:0 0 0 6px rgba(16,185,129,0)} 100%{transform:scale(.9);box-shadow:0 0 0 0 rgba(16,185,129,0)} }
@keyframes pr { 0%{transform:scale(.9);box-shadow:0 0 0 0 rgba(239,68,68,.7)} 70%{transform:scale(1.1);box-shadow:0 0 0 6px rgba(239,68,68,0)} 100%{transform:scale(.9);box-shadow:0 0 0 0 rgba(239,68,68,0)} }

/* ── Terminal ── */
.terminal {
    background:#020509; border:1px solid rgba(255,255,255,0.07); border-radius:12px;
    padding:14px 16px; font-family:'JetBrains Mono','Courier New',monospace;
    height:300px; overflow-y:auto;
    box-shadow:inset 0 2px 8px rgba(0,0,0,.9), 0 4px 20px rgba(0,0,0,.4);
}
.lg { margin-bottom:5px; font-size:0.78rem; line-height:1.45;
    border-bottom:1px solid rgba(255,255,255,0.02); padding-bottom:4px; }
.ts { color:#334155; margin-right:6px; }
.li { color:#38bdf8; } .lw { color:#fbbf24; } .le { color:#f87171; } .ls { color:#34d399; }
.lm { color:#cbd5e1; }

/* ── Progress bar ── */
.prog-wrap { background:rgba(255,255,255,0.05); border-radius:6px; height:7px; margin:6px 0 12px 0; overflow:hidden; }
.prog-fill { height:100%; border-radius:6px; transition:width .5s ease; }

/* ── Stat grid ── */
.stat-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.stat-item { background:rgba(255,255,255,0.025); border-radius:10px; padding:12px 14px; border:1px solid rgba(255,255,255,0.05); }
.stat-label { font-size:0.7rem; color:#475569; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; }
.stat-val { font-size:1.15rem; font-weight:700; margin-top:3px; }

div.stButton > button { border-radius:9px!important; font-weight:600!important; transition:all .2s ease!important; }
div.stButton > button:hover { transform:translateY(-1px); box-shadow:0 4px 14px rgba(99,102,241,.25)!important; }
.stSlider [data-baseweb="slider"] { padding-top:8px; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
h1, h2 = st.columns([5, 2])
with h1:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:16px;">
        <span style="font-size:2.4rem;filter:drop-shadow(0 0 14px rgba(99,102,241,.6));">⚡</span>
        <div>
            <h1 style="margin:0;padding:0;font-size:2rem;background:linear-gradient(90deg,#fff 25%,#a5b4fc 65%,#6366f1 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">
                SCALPER ALGORÍTMICO BINGX</h1>
            <p style="margin:0;color:#475569;font-size:0.85rem;">Sistema de Ejecución Autónoma · BingX VST Demo · Motor Multi-Activo</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
with h2:
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    led_cls = "led-g" if is_running else "led-r"
    led_txt = "MOTOR ACTIVO" if is_running else "MOTOR EN PAUSA"
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    st.markdown(f"""
    <div style="text-align:right;">
        <div class="led-wrap"><div class="{led_cls}"></div><span>{led_txt}</span></div>
        <div style="color:#334155;font-size:0.72rem;margin-top:6px;font-family:'JetBrains Mono';">
            Última actualización: {now_str} · {open_positions_count}/10 posiciones
        </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

# ── KPI Row 1 (6 cards) ───────────────────────────────────────────────────────
k1,k2,k3,k4,k5,k6 = st.columns(6)

def kpi(col, label, value, sub, cls, icon):
    col.markdown(f"""
    <div class="kpi-card {cls}">
        <div class="kpi-label">{icon} {label}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>""", unsafe_allow_html=True)

kpi(k1, "Saldo VST", f"{balance:,.0f}", "💵 Fondos disponibles", "blue", "")
pnl_c = "green" if open_pnl >= 0 else "red"
pnl_col = "#10b981" if open_pnl >= 0 else "#ef4444"
k2.markdown(f"""
<div class="kpi-card {pnl_c}">
    <div class="kpi-label">📈 PnL Abierto</div>
    <div class="kpi-value" style="color:{pnl_col};">{open_pnl:+,.2f}</div>
    <div class="kpi-sub">{open_positions_count} pos · ${total_exposure:,.0f} expuesto</div>
</div>""", unsafe_allow_html=True)

np_c = "green" if net_profit >= 0 else "red"
np_col = "#10b981" if net_profit >= 0 else "#ef4444"
k3.markdown(f"""
<div class="kpi-card {np_c}">
    <div class="kpi-label">💰 Beneficio Neto</div>
    <div class="kpi-value" style="color:{np_col};">{net_profit:+,.2f}</div>
    <div class="kpi-sub">VST realizado acumulado</div>
</div>""", unsafe_allow_html=True)

wr_c = "green" if win_rate >= 55 else ("amber" if win_rate >= 45 else "red")
wr_col = "#10b981" if win_rate >= 55 else ("#f59e0b" if win_rate >= 45 else "#ef4444")
k4.markdown(f"""
<div class="kpi-card {wr_c}">
    <div class="kpi-label">🏆 Win Rate</div>
    <div class="kpi-value" style="color:{wr_col};">{win_rate:.1f}%</div>
    <div class="kpi-sub">{win_trades}W / {loss_trades}L · {total_trades} total</div>
</div>""", unsafe_allow_html=True)

kpi(k5, "Trades Hoy", f"{len(trades_today)}", f"PnL hoy: {pnl_today:+.2f} VST", "cyan", "📅")
kpi(k6, "Max Drawdown", f"{max_drawdown:,.2f}", "VST caída máx registrada", "red", "📉")

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ── KPI Row 2 (stats row) ─────────────────────────────────────────────────────
s1,s2,s3,s4,s5,s6 = st.columns(6)
pf_col = "#10b981" if profit_factor >= 1.5 else ("#f59e0b" if profit_factor >= 1 else "#ef4444")
s1.markdown(f"""<div class="kpi-card blue" style="min-height:80px;padding:14px 16px;">
<div class="kpi-label">⚖️ Profit Factor</div>
<div class="kpi-value" style="font-size:1.35rem;color:{pf_col};">{profit_factor:.2f}</div></div>""", unsafe_allow_html=True)
s2.markdown(f"""<div class="kpi-card green" style="min-height:80px;padding:14px 16px;">
<div class="kpi-label">✅ Ganancia Media</div>
<div class="kpi-value" style="font-size:1.35rem;color:#10b981;">{avg_win:+.2f}</div></div>""", unsafe_allow_html=True)
s3.markdown(f"""<div class="kpi-card red" style="min-height:80px;padding:14px 16px;">
<div class="kpi-label">❌ Pérdida Media</div>
<div class="kpi-value" style="font-size:1.35rem;color:#ef4444;">{avg_loss:.2f}</div></div>""", unsafe_allow_html=True)
rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0
s4.markdown(f"""<div class="kpi-card purple" style="min-height:80px;padding:14px 16px;">
<div class="kpi-label">📐 Ratio R:R</div>
<div class="kpi-value" style="font-size:1.35rem;color:#a855f7;">1 : {rr:.2f}</div></div>""", unsafe_allow_html=True)
s5.markdown(f"""<div class="kpi-card amber" style="min-height:80px;padding:14px 16px;">
<div class="kpi-label">🔓 Pos. Abiertas</div>
<div class="kpi-value" style="font-size:1.35rem;color:#f59e0b;">{open_positions_count} / 10</div></div>""", unsafe_allow_html=True)
s6.markdown(f"""<div class="kpi-card cyan" style="min-height:80px;padding:14px 16px;">
<div class="kpi-label">💼 Exposición Total</div>
<div class="kpi-value" style="font-size:1.35rem;color:#06b6d4;">${total_exposure:,.0f}</div></div>""", unsafe_allow_html=True)

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

# ── Control bar (full width, compact) ─────────────────────────────────────────
cb1, cb2, cb3, cb4 = st.columns([2, 2, 2, 6])
tog_lbl = "⏸ PAUSAR MOTOR" if is_running else "▶ INICIAR MOTOR"
if cb1.button(tog_lbl, use_container_width=True, type="secondary" if is_running else "primary"):
    update_state('running_state', "0" if is_running else "1")
    log_message('INFO', f"Motor {'pausado' if is_running else 'activado'} manualmente.")
    st.rerun()

sym_opts = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'DOGE-USDT', 'BNB-USDT', 'ADA-USDT']
active_idx = sym_opts.index(active_symbol) if active_symbol in sym_opts else 0
sel_sym = cb2.selectbox("Par de referencia", sym_opts, index=active_idx, label_visibility="collapsed")
if sel_sym != active_symbol:
    update_state('selected_symbol', sel_sym)
    st.rerun()

cur_lev = int(get_state('leverage') or 10)
sel_lev = int(cb3.number_input("Apalancamiento", min_value=1, max_value=50, value=cur_lev, step=1, label_visibility="collapsed"))
if sel_lev != cur_lev:
    update_state('leverage', sel_lev)

# Win rate + exposure progress inline
wr_w = min(int(win_rate), 100)
wr_col2 = "#10b981" if win_rate >= 55 else ("#f59e0b" if win_rate >= 45 else "#ef4444")
exp_pct = min(int(open_positions_count / 10 * 100), 100)
exp_color = "#10b981" if exp_pct < 60 else ("#f59e0b" if exp_pct < 90 else "#ef4444")
cb4.markdown(f"""
<div style="display:flex;gap:30px;align-items:center;padding:8px 4px;">
    <div style="flex:1;">
        <div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#475569;margin-bottom:3px;">
            <span>Win Rate</span><span style="color:{wr_col2};font-weight:700;">{win_rate:.1f}%</span>
        </div>
        <div class="prog-wrap"><div class="prog-fill" style="width:{wr_w}%;background:{wr_col2};"></div></div>
    </div>
    <div style="flex:1;">
        <div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#475569;margin-bottom:3px;">
            <span>Posiciones</span><span style="color:{exp_color};font-weight:700;">{open_positions_count}/10</span>
        </div>
        <div class="prog-wrap"><div class="prog-fill" style="width:{exp_pct}%;background:{exp_color};"></div></div>
    </div>
    <div style="flex:1;">
        <div style="font-size:0.72rem;color:#475569;margin-bottom:3px;">Parámetros Activos</div>
        <div style="font-size:0.78rem;color:#94a3b8;">
            <span style="color:#6366f1;font-weight:600;">10×</span> Lev · 
            <span style="color:#ef4444;">4×ATR</span> SL · 
            <span style="color:#10b981;">2×R</span> TP · 
            <span style="color:#f59e0b;">BE@40%</span> · 
            <span style="color:#a855f7;">Trail@75%</span> · 
            <span style="color:#06b6d4;">$20/trade</span>
        </div>
    </div>
</div>""", unsafe_allow_html=True)



# ── Monitor de Posiciones Activas ─────────────────────────────────────────────
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
st.markdown('<div class="section-hdr">🔓 Monitor de Posiciones Activas — Futuros Perpetuos BingX VST</div>', unsafe_allow_html=True)

if df_positions.empty:
    st.markdown("""
    <div style="background:rgba(255,255,255,0.01);border:1px dashed rgba(255,255,255,0.08);
        border-radius:12px;padding:28px;text-align:center;color:#475569;">
        ⚪ Sin posiciones activas. El bot escaneará señales en el próximo ciclo de 15s.
    </div>""", unsafe_allow_html=True)
else:
    st.markdown("""<div class="pos-hdr">
        <span>Símbolo</span><span>Lado</span><span>Tamaño</span>
        <span>Entrada</span><span>Lev.</span><span>PnL VST</span>
        <span>Stop Loss</span><span>Take Profit</span><span>Acción</span>
    </div>""", unsafe_allow_html=True)

    for index, row in df_positions.iterrows():
        side_badge = '<span class="badge-long">LONG</span>' if row['side'] == 'LONG' else '<span class="badge-short">SHORT</span>'
        pnl_val = row['unrealized_pnl'] or 0.0
        pnl_color = "#10b981" if pnl_val >= 0 else "#ef4444"
        sl_val = row.get('sl') or 0
        tp_val = row.get('tp') or 0
        sl_str = f"${sl_val:,.4f}" if sl_val and sl_val > 0 else "—"
        tp_str = f"${tp_val:,.4f}" if tp_val and tp_val > 0 else "—"
        entry_p = row['entry_price'] or 0
        entry_str = f"${entry_p:,.4f}" if entry_p > 0 else "—"

        pc = st.columns([1.4, 0.7, 1, 1, 0.5, 1, 1.1, 1.1, 0.7])
        pc[0].markdown(f"**{row['symbol']}**")
        pc[1].markdown(side_badge, unsafe_allow_html=True)
        pc[2].markdown(f"<span class='mono'>{row['size']:.4f}</span>", unsafe_allow_html=True)
        pc[3].markdown(f"<span class='mono'>{entry_str}</span>", unsafe_allow_html=True)
        pc[4].markdown(f"**{row['leverage']}x**")
        pc[5].markdown(f"<span style='color:{pnl_color};font-weight:700;'>{pnl_val:+.2f}</span>", unsafe_allow_html=True)
        pc[6].markdown(f"<span style='color:#f87171;font-size:0.8rem;' class='mono'>{sl_str}</span>", unsafe_allow_html=True)
        pc[7].markdown(f"<span style='color:#34d399;font-size:0.8rem;' class='mono'>{tp_str}</span>", unsafe_allow_html=True)
        if pc[8].button("✕", key=f"cb_{row['id']}", use_container_width=True):
            close_position(row['id'])
            st.rerun()

# ── Rendimiento Global + Distribución PnL ─────────────────────────────────────
st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
perf_col, dist_col, sym_col = st.columns([2, 2, 1.5])

with perf_col:
    st.markdown('<div class="section-hdr">📊 Rendimiento Global</div>', unsafe_allow_html=True)
    rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    pf_col2 = "#10b981" if profit_factor >= 1.5 else ("#f59e0b" if profit_factor >= 1 else "#ef4444")
    st.markdown(f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="stat-item"><div class="stat-label">Win Rate</div>
            <div class="stat-val" style="color:{wr_col2};">{win_rate:.1f}%</div></div>
        <div class="stat-item"><div class="stat-label">Profit Factor</div>
            <div class="stat-val" style="color:{pf_col2};">{profit_factor:.2f}</div></div>
        <div class="stat-item"><div class="stat-label">Ganancia Media</div>
            <div class="stat-val" style="color:#10b981;">{avg_win:+.2f}</div></div>
        <div class="stat-item"><div class="stat-label">Pérdida Media</div>
            <div class="stat-val" style="color:#ef4444;">{avg_loss:.2f}</div></div>
        <div class="stat-item"><div class="stat-label">Ratio R:R</div>
            <div class="stat-val" style="color:#a855f7;">1 : {rr:.2f}</div></div>
        <div class="stat-item"><div class="stat-label">Max Drawdown</div>
            <div class="stat-val" style="color:#ef4444;">{max_drawdown:,.2f}</div></div>
        <div class="stat-item"><div class="stat-label">Trades Totales</div>
            <div class="stat-val">{total_trades}</div></div>
        <div class="stat-item"><div class="stat-label">PnL Hoy</div>
            <div class="stat-val" style="color:{'#10b981' if pnl_today>=0 else '#ef4444'};">{pnl_today:+.2f}</div></div>
    </div>
    """, unsafe_allow_html=True)

with dist_col:
    st.markdown('<div class="section-hdr">📉 Distribución de PnL</div>', unsafe_allow_html=True)
    if not df_trades.empty and len(df_trades) >= 2:
        fig_dist = go.Figure()
        wins_pnl = df_trades[df_trades['result'] == 'WIN']['pnl']
        losses_pnl = df_trades[df_trades['result'] == 'LOSS']['pnl']
        if len(wins_pnl) > 0:
            fig_dist.add_trace(go.Histogram(x=wins_pnl, name='WIN',
                marker_color='rgba(16,185,129,0.65)', nbinsx=12))
        if len(losses_pnl) > 0:
            fig_dist.add_trace(go.Histogram(x=losses_pnl, name='LOSS',
                marker_color='rgba(239,68,68,0.65)', nbinsx=12))
        fig_dist.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(5,7,15,0.5)',
            height=220, margin=dict(l=0,r=0,t=5,b=0), barmode='overlay',
            xaxis=dict(gridcolor='rgba(255,255,255,0.03)', tickfont=dict(color='#334155',size=9)),
            yaxis=dict(gridcolor='rgba(255,255,255,0.03)', tickfont=dict(color='#334155',size=9)),
            legend=dict(font=dict(color='#64748b',size=9), bgcolor='rgba(0,0,0,0)',
                        orientation='h', y=1.08, x=0)
        )
        st.plotly_chart(fig_dist, use_container_width=True, config={'displayModeBar': False})
    else:
        st.markdown('<div style="color:#334155;font-size:0.85rem;padding:20px 0;">Sin datos suficientes aún.</div>', unsafe_allow_html=True)

with sym_col:
    st.markdown('<div class="section-hdr">🏅 PnL por Símbolo</div>', unsafe_allow_html=True)
    if not df_trades.empty:
        sym_pnl = df_trades.groupby('symbol')['pnl'].sum().sort_values(ascending=False).head(8)
        for sym, pval in sym_pnl.items():
            pc2 = "#10b981" if pval >= 0 else "#ef4444"
            bar_w = min(abs(pval) / max(sym_pnl.abs().max(), 1) * 100, 100)
            st.markdown(f"""
            <div style="padding:7px 10px;border-radius:8px;background:rgba(255,255,255,0.02);
                border:1px solid rgba(255,255,255,0.04);margin-bottom:5px;">
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:3px;">
                    <span style="font-weight:600;">{sym}</span>
                    <span style="color:{pc2};font-weight:700;font-family:'JetBrains Mono';">{pval:+.2f}</span>
                </div>
                <div style="background:rgba(255,255,255,0.04);border-radius:4px;height:4px;">
                    <div style="width:{bar_w:.0f}%;height:100%;border-radius:4px;background:{pc2};opacity:0.7;"></div>
                </div>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown('<div style="color:#334155;font-size:0.85rem;padding:20px 0;">Sin historial.</div>', unsafe_allow_html=True)

# ── Historial de Trades ────────────────────────────────────────────────────────
st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
st.markdown('<div class="section-hdr">📋 Historial de Trades</div>', unsafe_allow_html=True)

if df_trades.empty:
    st.markdown('<div style="color:#334155;font-size:0.85rem;padding:10px 0;">Sin operaciones registradas aún.</div>', unsafe_allow_html=True)
else:
    df_show = df_trades.head(30).copy()
    df_show['PnL'] = df_show['pnl'].apply(lambda x: f"{x:+.2f}")
    
    def format_result(row):
        res_str = "✅ WIN" if row['result'] == 'WIN' else "❌ LOSS"
        reason = row.get('exit_reason')
        if pd.notna(reason) and reason:
            reason_map = {"STOP_LOSS": "SL", "TAKE_PROFIT": "TP", "PROTECTED_STOP": "TRAIL"}
            reason_short = reason_map.get(reason, str(reason))
            return f"{res_str} [{reason_short}]"
        return res_str
        
    df_show['Resultado'] = df_show.apply(format_result, axis=1)
    df_show['Entrada'] = df_show['entry_price'].apply(lambda x: f"${x:,.4f}")
    df_show['Salida'] = df_show['exit_price'].apply(lambda x: f"${x:,.4f}")
    df_show['Lev'] = df_show['leverage'].apply(lambda x: f"{x}x")
    display_df = df_show[['timestamp','symbol','side','size','Entrada','Salida','Lev','PnL','Resultado']].rename(columns={
        'timestamp':'Fecha','symbol':'Par','side':'Lado','size':'Tamaño'})
    st.dataframe(display_df, use_container_width=True, hide_index=True,
        column_config={
            "Fecha": st.column_config.TextColumn(width="medium"),
            "Par": st.column_config.TextColumn(width="small"),
            "Lado": st.column_config.TextColumn(width="small"),
            "PnL": st.column_config.TextColumn(width="small"),
            "Resultado": st.column_config.TextColumn(width="small"),
        })

# ── Terminal de Ejecución ──────────────────────────────────────────────────────
st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
st.markdown('<div class="section-hdr">🖥️ Terminal de Ejecución en Tiempo Real</div>', unsafe_allow_html=True)

df_logs = get_logs(60)
log_html = '<div class="terminal" id="term-log">'
level_map = {'SUCCESS': 'ls', 'WARNING': 'lw', 'ERROR': 'le', 'INFO': 'li'}
for _, row in df_logs.iterrows():
    lv = row['level']
    cls = level_map.get(lv, 'li')
    msg = str(row['message']).replace('<', '&lt;').replace('>', '&gt;')
    log_html += f'<div class="lg"><span class="ts">[{row["timestamp"]}]</span><span class="{cls}">[{lv}]</span> <span class="lm">{msg}</span></div>'
log_html += '</div>'
st.markdown(log_html, unsafe_allow_html=True)
st.markdown("""<script>var t=document.getElementById("term-log");if(t)t.scrollTop=t.scrollHeight;</script>""", unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center;color:#1e293b;font-size:0.72rem;margin-top:20px;font-family:'JetBrains Mono';">
    BingX VST Scalper Bot v2.1 · sqlite://bot.db · Motor: {'ACTIVO ●' if is_running else 'PAUSADO ○'} ·
    {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
</div>""", unsafe_allow_html=True)

# Auto-refresh cada 15 segundos
st.markdown("""<script>setTimeout(function(){ window.location.reload(); }, 15000);</script>""", unsafe_allow_html=True)

