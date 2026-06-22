import sqlite3
import os
import sys
from datetime import datetime, timezone

# Add the parent directory to sys.path to easily import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from config import DB_PATH
except ImportError:
    # Fallback if config is not importable
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading.db")

def get_connection():
    """Returns a connection to the SQLite database. Creates parent folders if they don't exist."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Returns rows that can be accessed like dictionaries
    return conn

def init_db():
    """Initializes the database schema."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Config Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT UNIQUE NOT NULL,
        leverage INTEGER NOT NULL DEFAULT 20,
        risk REAL NOT NULL DEFAULT 0.02,
        is_active INTEGER NOT NULL DEFAULT 1
    )
    """)
    
    # 2. Positions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT UNIQUE NOT NULL,
        side TEXT NOT NULL,          -- 'LONG' or 'SHORT'
        entry_price REAL NOT NULL,
        size REAL NOT NULL,
        sl REAL,
        tp REAL,
        pnl REAL DEFAULT 0.0,
        ts TEXT NOT NULL             -- Timestamp ISO format
    )
    """)
    
    # 3. Trades Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        entry_price REAL NOT NULL,
        exit_price REAL NOT NULL,
        size REAL NOT NULL,
        pnl REAL NOT NULL,
        duration REAL,               -- Duration in seconds
        exit_reason TEXT,            -- 'SL', 'TP', 'MANUAL', etc.
        ts TEXT NOT NULL
    )
    """)
    
    # 4. Logs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level TEXT NOT NULL,         -- 'INFO', 'WARNING', 'ERROR', 'DEBUG'
        message TEXT NOT NULL,
        ts TEXT NOT NULL
    )
    """)
    
    # Insert a default config if table is empty
    cursor.execute("SELECT COUNT(*) FROM config")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO config (symbol, leverage, risk, is_active) VALUES (?, ?, ?, ?)",
            ("BTC-USDT", 20, 0.02, 1)
        )
    
    conn.commit()
    conn.close()

# --- Config Queries ---

def get_config(symbol="BTC-USDT"):
    """Fetches configuration for a specific symbol."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM config WHERE symbol = ?", (symbol,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_active_config():
    """Fetches the active configuration (where is_active = 1)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM config WHERE is_active = 1 LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_config(symbol, leverage, risk, is_active=1):
    """Updates or inserts the config for a symbol."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO config (symbol, leverage, risk, is_active)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(symbol) DO UPDATE SET
        leverage = excluded.leverage,
        risk = excluded.risk,
        is_active = excluded.is_active
    """, (symbol, leverage, risk, is_active))
    conn.commit()
    conn.close()

# --- Positions Queries ---

def get_position(symbol):
    """Fetches open position for a symbol."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_positions():
    """Fetches all open positions."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM positions")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_position(symbol, side, entry_price, size, sl=None, tp=None, pnl=0.0):
    """Saves or updates an open position."""
    ts = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO positions (symbol, side, entry_price, size, sl, tp, pnl, ts)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(symbol) DO UPDATE SET
        side = excluded.side,
        entry_price = excluded.entry_price,
        size = excluded.size,
        sl = excluded.sl,
        tp = excluded.tp,
        pnl = excluded.pnl,
        ts = excluded.ts
    """, (symbol, side.upper(), entry_price, size, sl, tp, pnl, ts))
    conn.commit()
    conn.close()

def update_position_pnl(symbol, pnl):
    """Updates the unrealized PnL of an open position."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE positions SET pnl = ? WHERE symbol = ?", (pnl, symbol))
    conn.commit()
    conn.close()

def delete_position(symbol):
    """Deletes an open position when closed."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
    conn.commit()
    conn.close()

# --- Trades Queries ---

def add_trade(symbol, side, entry_price, exit_price, size, pnl, duration=None, exit_reason=None):
    """Records a completed trade in the history."""
    ts = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO trades (symbol, side, entry_price, exit_price, size, pnl, duration, exit_reason, ts)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (symbol, side.upper(), entry_price, exit_price, size, pnl, duration, exit_reason, ts))
    conn.commit()
    conn.close()

def get_recent_trades(limit=50):
    """Fetches recent trade history."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades ORDER BY ts DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# --- Logs Queries ---

def add_log(level, message):
    """Saves a system log entry to the DB."""
    ts = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO logs (level, message, ts)
    VALUES (?, ?, ?)
    """, (level.upper(), message, ts))
    conn.commit()
    conn.close()

def get_recent_logs(limit=100, level=None):
    """Fetches recent log entries."""
    conn = get_connection()
    cursor = conn.cursor()
    if level:
        cursor.execute("SELECT * FROM logs WHERE level = ? ORDER BY ts DESC LIMIT ?", (level.upper(), limit))
    else:
        cursor.execute("SELECT * FROM logs ORDER BY ts DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# Automatically initialize database if run directly
if __name__ == "__main__":
    print(f"Initializing database at: {DB_PATH}")
    init_db()
    print("Database initialized successfully.")
    
    # Simple test queries
    print("Configuring initial active symbol...")
    update_config("BTC-USDT", 20, 0.02, 1)
    cfg = get_active_config()
    print("Active Config:", cfg)
    
    print("Adding a test log...")
    add_log("INFO", "Database test run completed successfully.")
    print("Recent Logs:", get_recent_logs(5))
