import os
import sys
import time
import sqlite3
import logging
import datetime
from typing import Dict, Any, Optional
import numpy as np

# Add root folder to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exchange.bingx_client import BingXClient
from strategy.scalping import (
    calculate_vwap,
    calculate_atr,
    calculate_institutional_features,
    generate_institutional_signals,
    KellySizer,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ExecutionEngine")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot.db")

MAX_OPEN_POSITIONS = 10
TOP_VOLUME_SYMBOL_LIMIT = 80
ENTRY_MARGIN_USDT = 20.0
ENTRY_LEVERAGE = 10
ENTRY_EXPOSURE_USDT = ENTRY_MARGIN_USDT * ENTRY_LEVERAGE
AGGRESSIVE_LIMIT_CROSS_BPS = 2.0
MAX_ENTRY_SPREAD_BPS = 8.0
MIN_TOP_OF_BOOK_NOTIONAL_USDT = ENTRY_EXPOSURE_USDT * 0.50
MIN_OBI_CONFIRMATION = 0.08
MIN_MICROPRICE_EDGE_BPS = 0.005
STOP_LOSS_ATR_MULTIPLIER = 4.0
TAKE_PROFIT_R_MULTIPLIER = 2.0
BREAKEVEN_TRIGGER_PROGRESS = 0.40
BREAKEVEN_LOCK_PROGRESS = 0.25
TRAILING_TRIGGER_PROGRESS = 0.75
TRAILING_DISTANCE_PROGRESS = 0.12

class ExecutionTrader:
    """
    Autonomous high-frequency execution trader.
    Runs a persistent loop executing indicators, signals, risk-management,
    and automatic failover to simulated paper trading if API keys fail.
    """
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()
        self._init_db_columns()
        
        # Load API keys from config/DB
        self.client = BingXClient()
        self.sizer = KellySizer(db_path=self.db_path)
        
        self.simulation_mode = False
        self.last_candle_time = None
        self.symbols_list = []
        self.last_symbols_update = 0
        
        self._check_api_connection()
        self._start_stay_alive_pinger()
        
    def _start_stay_alive_pinger(self):
        """Starts a background thread that self-pings the Hugging Face Space to prevent idle sleep."""
        import threading
        
        def ping_loop():
            logger.info("Stay-Alive / Keep-Awake pinger thread activated.")
            import requests
            # Wait 1 minute on startup before pinging
            time.sleep(60)
            while True:
                try:
                    # Direct Space embed URL
                    url = "https://luisalbertor-botbingx.hf.space"
                    r = requests.get(url, timeout=15)
                    logger.info(f"Sent Keep-Awake self-ping to {url}. Response status: {r.status_code}")
                except Exception as e:
                    logger.debug(f"Stay-Alive self-ping exception: {e}")
                # Ping every 15 minutes (900 seconds)
                time.sleep(900)
                
        t = threading.Thread(target=ping_loop, name="StayAlivePingerThread", daemon=True)
        t.start()
        
    def _init_db(self):
        """Initializes the database schema if it doesn't exist yet, replicating app.py structure."""
        try:
            db_dir = os.path.dirname(self.db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            ''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                side TEXT,
                size REAL,
                entry_price REAL,
                leverage INTEGER,
                unrealized_pnl REAL,
                timestamp TEXT
            )
            ''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                side TEXT,
                size REAL,
                entry_price REAL,
                exit_price REAL,
                leverage INTEGER,
                pnl REAL,
                timestamp TEXT,
                result TEXT
            )
            ''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                level TEXT,
                message TEXT
            )
            ''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS cooldowns (
                symbol TEXT PRIMARY KEY,
                until TEXT
            )
            ''')
            
            # Populate default bot states if empty
            cursor.execute("SELECT COUNT(*) FROM bot_state")
            if cursor.fetchone()[0] == 0:
                cursor.execute("INSERT INTO bot_state (key, value) VALUES ('running_state', '1')")
                cursor.execute("INSERT INTO bot_state (key, value) VALUES ('vst_balance', '100000.0')")
                cursor.execute("INSERT INTO bot_state (key, value) VALUES ('risk_per_trade', '1.5')")
                cursor.execute("INSERT INTO bot_state (key, value) VALUES ('leverage', '20')")
                cursor.execute("INSERT INTO bot_state (key, value) VALUES ('selected_symbol', 'BTC-USDT')")
                
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error initializing SQLite database tables: {e}")
        
    def _init_db_columns(self):
        """Alters the positions and trades tables to ensure compatible schemas."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Migrate positions table
            try:
                cursor.execute("ALTER TABLE positions ADD COLUMN sl REAL")
            except sqlite3.OperationalError:
                pass  # sl column already exists
                
            try:
                cursor.execute("ALTER TABLE positions ADD COLUMN tp REAL")
            except sqlite3.OperationalError:
                pass  # tp column already exists

            position_columns = {
                "initial_sl": "REAL",
                "initial_tp": "REAL",
                "peak_price": "REAL",
                "breakeven_active": "INTEGER DEFAULT 0",
                "trailing_active": "INTEGER DEFAULT 0",
                "take_profit_active": "INTEGER DEFAULT 1",
            }
            for column_name, column_type in position_columns.items():
                try:
                    cursor.execute(f"ALTER TABLE positions ADD COLUMN {column_name} {column_type}")
                except sqlite3.OperationalError:
                    pass
                
            # Migrate trades table
            try:
                cursor.execute("ALTER TABLE trades ADD COLUMN size REAL")
            except sqlite3.OperationalError:
                pass
                
            try:
                cursor.execute("ALTER TABLE trades ADD COLUMN leverage INTEGER")
            except sqlite3.OperationalError:
                pass
                
            try:
                cursor.execute("ALTER TABLE trades ADD COLUMN result TEXT")
            except sqlite3.OperationalError:
                pass
                
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error altering database columns during migration: {e}")

    def _check_api_connection(self):
        """Verifica la validez de la llave API y activa la contingencia de simulacion si falla."""
        logger.info("Verificando autenticacion de llaves de API BingX...")
        res = self.client.get_balance("VST")
        if res == 0.0:
            test_res = self.client._request("GET", "/openApi/swap/v2/user/balance")
            if not test_res["success"] and test_res["code"] == 100413:
                logger.warning("="*60)
                logger.warning("FALLO LA AUTENTICACION DE LLAVES DE API BINGX: apiKey incorrecta!")
                logger.warning("ACTIVANDO MODO DE SIMULACION DE PAPER TRADING LOCAL (CONTINGENCIA ACTIVA)")
                logger.warning("="*60)
                self.simulation_mode = True
                self.log_to_db("WARNING", "Fallo de autenticacion API. Activando contingencia de Paper Trading.")
            else:
                logger.info("Conexion exitosa a la API de BingX (Modo Demo VST). El saldo esta activo.")
                self.log_to_db("SUCCESS", "Conectado a la API Demo de Futuros Perpetuos de BingX.")
                self.client.ensure_hedge_mode()
                self._sync_positions_from_exchange()   # Sincronizar al arranque
        else:
            logger.info("Conexion exitosa a la API de BingX (Modo Demo VST). El saldo esta activo.")
            self.log_to_db("SUCCESS", "Conectado a la API Demo de Futuros Perpetuos de BingX.")
            self.client.ensure_hedge_mode()
            self._sync_positions_from_exchange()       # Sincronizar al arranque

    def _sync_positions_from_exchange(self):
        """
        Sincroniza las posiciones locales con el exchange BingX.
        - Elimina posiciones locales que NO existen en el exchange (fantasmas).
        - Elimina posiciones con entry_price <= 0 (IOC no ejecutados).
        - Inserta posiciones reales del exchange que no esten en la DB local.
        Solo se ejecuta en modo real (no simulacion).
        """
        if self.simulation_mode:
            return
        try:
            exchange_positions = self.client.get_positions()
            real_keys = {
                (p["symbol"], p["side"])
                for p in exchange_positions
                if float(p.get("entry_price", 0)) > 0
            }

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM positions")
            local_positions = [dict(r) for r in cursor.fetchall()]

            removed = 0
            for pos in local_positions:
                key = (pos["symbol"], pos["side"])
                entry_p = float(pos.get("entry_price") or 0)
                # Remove ghost: entry_price=0 OR not found on exchange
                if entry_p <= 0 or key not in real_keys:
                    cursor.execute("DELETE FROM positions WHERE id = ?", (pos["id"],))
                    logger.warning(
                        f"Posicion fantasma eliminada: {pos['symbol']} {pos['side']} "
                        f"(entry={entry_p}, en_exchange={key in real_keys})"
                    )
                    self.log_to_db("WARNING",
                        f"Posicion fantasma purgada: {pos['symbol']} {pos['side']} entry=${entry_p}")
                    removed += 1

            # Insert any real exchange positions not in local DB
            local_keys = {
                (p["symbol"], p["side"])
                for p in local_positions
                if float(p.get("entry_price") or 0) > 0
            }
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            added = 0
            for p in exchange_positions:
                key = (p["symbol"], p["side"])
                entry_p = float(p.get("entry_price", 0))
                if entry_p <= 0 or key in local_keys:
                    continue
                size = float(p["size"])
                lev = int(p.get("leverage", ENTRY_LEVERAGE))
                stop_pct, tp_pct = 0.02, 0.03
                if p["side"] == "LONG":
                    sl = entry_p * (1 - stop_pct)
                    tp = entry_p * (1 + tp_pct)
                else:
                    sl = entry_p * (1 + stop_pct)
                    tp = entry_p * (1 - tp_pct)
                cursor.execute("""
                    INSERT INTO positions
                    (symbol, side, size, entry_price, leverage, unrealized_pnl, timestamp,
                     sl, tp, initial_sl, initial_tp, peak_price,
                     breakeven_active, trailing_active, take_profit_active)
                    VALUES (?, ?, ?, ?, ?, 0.0, ?, ?, ?, ?, ?, ?, 0, 0, 1)
                """, (p["symbol"], p["side"], size, entry_p, lev, ts, sl, tp, sl, tp, entry_p))
                logger.info(f"Posicion del exchange sincronizada en DB: {p['symbol']} {p['side']} {size} @ ${entry_p}")
                self.log_to_db("INFO", f"Posicion sincronizada desde exchange: {p['symbol']} {p['side']} @ ${entry_p}")
                added += 1

            conn.commit()
            conn.close()
            if removed or added:
                logger.info(f"Sincronizacion completa: {removed} fantasmas eliminadas, {added} posiciones reales importadas.")
        except Exception as e:
            logger.error(f"Error durante sincronizacion de posiciones con exchange: {e}")

    def log_to_db(self, level: str, message: str):
        """Inserts system logs into the dashboard's database table."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("INSERT INTO logs (timestamp, level, message) VALUES (?, ?, ?)", (ts, level.upper(), message))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to write log to DB: {e}")

    def get_bot_state(self) -> Dict[str, Any]:
        """Fetches the current control configurations from the bot_state table."""
        state = {
            "running_state": False,
            "vst_balance": 100000.0,
            "risk_per_trade": 1.5,
            "leverage": 20,
            "selected_symbol": "BTC-USDT"
        }
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM bot_state")
            rows = cursor.fetchall()
            conn.close()
            
            for key, val in rows:
                if key == "running_state":
                    state["running_state"] = (val == "1")
                elif key == "vst_balance":
                    state["vst_balance"] = float(val)
                elif key == "risk_per_trade":
                    state["risk_per_trade"] = float(val)
                elif key == "leverage":
                    state["leverage"] = int(val)
                elif key == "selected_symbol":
                    state["selected_symbol"] = val
        except Exception as e:
            logger.error(f"Failed to read bot state from DB: {e}")
            
        return state

    def update_balance_in_db(self, new_balance: float):
        """Updates the local virtual balance in the bot_state table."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES ('vst_balance', ?)", (str(new_balance),))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to update balance in DB: {e}")

    def is_in_cooldown(self, symbol: str) -> bool:
        """Checks if a symbol is currently in cooldown mode."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT until FROM cooldowns WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            conn.close()
            if row:
                until_time = datetime.datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                if datetime.datetime.now() < until_time:
                    return True
                else:
                    # Cooldown expired, clean it up
                    conn = sqlite3.connect(self.db_path)
                    conn.execute("DELETE FROM cooldowns WHERE symbol = ?", (symbol,))
                    conn.commit()
                    conn.close()
        except Exception as e:
            logger.error(f"Error checking cooldown: {e}")
        return False

    def set_cooldown(self, symbol: str, minutes: int = 30):
        """Sets a cooldown period for a symbol."""
        try:
            until_time = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
            until_str = until_time.strftime('%Y-%m-%d %H:%M:%S')
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO cooldowns (symbol, until) VALUES (?, ?)", (symbol, until_str))
            conn.commit()
            conn.close()
            logger.info(f"Cooldown de {minutes}m activado para {symbol}. No operara hasta {until_str}")
        except Exception as e:
            logger.error(f"Error setting cooldown: {e}")

    def get_open_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Reads open positions for symbol from the local database."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error fetching open position from DB: {e}")
            return None

    def get_open_position_symbols(self) -> set:
        """Returns the symbols currently held in the local position book."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT symbol FROM positions")
            symbols = {row[0] for row in cursor.fetchall()}
            conn.close()
            return symbols
        except Exception as e:
            logger.error(f"Error fetching open position symbols: {e}")
            return set()

    def get_active_positions_count(self) -> int:
        """Returns current local open-position count."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM positions")
            active_positions_count = cursor.fetchone()[0]
            conn.close()
            return active_positions_count
        except Exception as e:
            logger.error(f"Error fetching active positions count: {e}")
            return 0

    def calculate_aggressive_limit_price(self, symbol: str, side: str, fallback_price: float) -> float:
        """
        Creates a marketable limit price close to top-of-book.
        BUY crosses slightly above ask; SELL crosses slightly below bid.
        """
        top = self.client.get_best_bid_ask(symbol)
        if not top:
            return fallback_price

        cross = AGGRESSIVE_LIMIT_CROSS_BPS / 10_000
        if side == "LONG":
            return top["ask"] * (1 + cross)
        return top["bid"] * (1 - cross)

    def get_microstructure_confirmation(self, symbol: str, side: str) -> Dict[str, Any]:
        """
        Validates entry quality using top-of-book spread, depth, OBI, and microprice.
        This is a risk filter, not a standalone alpha.
        """
        data = self.client.get_order_book(symbol, limit=5)
        if not data:
            return {"allowed": False, "reason": "no_order_book"}

        try:
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if not bids or not asks:
                return {"allowed": False, "reason": "empty_order_book"}

            bid = float(bids[0][0])
            ask = float(asks[0][0])
            bid_size = float(bids[0][1])
            ask_size = float(asks[0][1])
            mid = (bid + ask) / 2
            if mid <= 0:
                return {"allowed": False, "reason": "invalid_mid"}

            spread_bps = (ask - bid) / mid * 10_000
            bid_vol = sum(float(level[1]) for level in bids[:5])
            ask_vol = sum(float(level[1]) for level in asks[:5])
            total_vol = bid_vol + ask_vol
            if total_vol <= 0:
                return {"allowed": False, "reason": "zero_depth"}

            obi = (bid_vol - ask_vol) / total_vol
            microprice = (ask * bid_size + bid * ask_size) / max(bid_size + ask_size, 1e-12)
            microprice_edge_bps = (microprice - mid) / mid * 10_000
            top_notional = min(bid * bid_size, ask * ask_size)

            if spread_bps > MAX_ENTRY_SPREAD_BPS:
                return {"allowed": False, "reason": "wide_spread", "obi": obi, "spread_bps": spread_bps, "microprice_edge_bps": microprice_edge_bps}
            if top_notional < MIN_TOP_OF_BOOK_NOTIONAL_USDT:
                return {"allowed": False, "reason": "thin_top_book", "obi": obi, "spread_bps": spread_bps, "microprice_edge_bps": microprice_edge_bps}
            if side == "LONG" and (obi < MIN_OBI_CONFIRMATION or microprice_edge_bps < MIN_MICROPRICE_EDGE_BPS):
                return {"allowed": False, "reason": "weak_buy_microstructure", "obi": obi, "spread_bps": spread_bps, "microprice_edge_bps": microprice_edge_bps}
            if side == "SHORT" and (obi > -MIN_OBI_CONFIRMATION or microprice_edge_bps > -MIN_MICROPRICE_EDGE_BPS):
                return {"allowed": False, "reason": "weak_sell_microstructure", "obi": obi, "spread_bps": spread_bps, "microprice_edge_bps": microprice_edge_bps}

            return {
                "allowed": True,
                "reason": "confirmed",
                "obi": obi,
                "spread_bps": spread_bps,
                "microprice_edge_bps": microprice_edge_bps,
                "bid": bid,
                "ask": ask,
                "top_notional": top_notional,
            }
        except Exception as e:
            logger.error(f"Error validating microstructure for {symbol}: {e}")
            return {"allowed": False, "reason": "microstructure_error"}

    def execute_entry_order(self, symbol: str, side: str, size: float, price: float, leverage: int, latest_atr: float) -> bool:
        """Executes an aggressive IOC limit entry and records only confirmed openings."""
        if self.get_active_positions_count() >= MAX_OPEN_POSITIONS:
            logger.info(f"Entrada bloqueada en {symbol}: ya hay {MAX_OPEN_POSITIONS} posiciones abiertas.")
            return False
        if symbol in self.get_open_position_symbols():
            logger.info(f"Entrada bloqueada en {symbol}: ya existe una posición abierta en ese par.")
            return False

        entry_price = price
        if not self.simulation_mode:
            # Set leverage first on the exchange
            self.client.set_leverage(symbol, "LONG" if side == "LONG" else "SHORT", leverage)
            
            limit_price = self.calculate_aggressive_limit_price(symbol, side, price)
            
            stop_distance = STOP_LOSS_ATR_MULTIPLIER * latest_atr
            take_profit_distance = TAKE_PROFIT_R_MULTIPLIER * stop_distance
            if side == "LONG":
                sl = limit_price - stop_distance
                tp = limit_price + take_profit_distance
            else:
                sl = limit_price + stop_distance
                tp = limit_price - take_profit_distance
                
            order_side = "BUY" if side == "LONG" else "SELL"
            pos_side = "LONG" if side == "LONG" else "SHORT"
            res = self.client.place_order(
                symbol, order_side, pos_side, "LIMIT", size, 
                price=limit_price, time_in_force="IOC",
                take_profit=None, stop_loss=sl
            )
            if not res["success"]:
                logger.error(f"Orden de ejecución rechazada por BingX: {res['msg']}")
                self.log_to_db("ERROR", f"Orden BingX rechazada para {symbol}: {res['msg']}")
                return False

            time.sleep(0.6)
            exchange_positions = self.client.get_positions(symbol)
            matching_position = next(
                (p for p in exchange_positions if p.get("symbol") == symbol and p.get("side") == side and float(p.get("size", 0.0)) > 0),
                None
            )
            if not matching_position:
                logger.warning(f"Limit IOC en {symbol} no confirmó posición abierta; no se registra localmente.")
                self.log_to_db("WARNING", f"Entrada LIMIT IOC en {symbol} no confirmó fill. Orden descartada para evitar posición fantasma.")
                return False

            entry_price = float(matching_position.get("entry_price", limit_price))
            size = float(matching_position.get("size", size))
        else:
            entry_price = self.calculate_aggressive_limit_price(symbol, side, price)
            stop_distance = STOP_LOSS_ATR_MULTIPLIER * latest_atr
            take_profit_distance = TAKE_PROFIT_R_MULTIPLIER * stop_distance
            if side == "LONG":
                sl = entry_price - stop_distance
                tp = entry_price + take_profit_distance
            else:
                sl = entry_price + stop_distance
                tp = entry_price - take_profit_distance

        # Write position to database
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                """
                INSERT INTO positions (
                    symbol, side, size, entry_price, leverage, unrealized_pnl, timestamp,
                    sl, tp, initial_sl, initial_tp, peak_price,
                    breakeven_active, trailing_active, take_profit_active
                )
                VALUES (?, ?, ?, ?, ?, 0.0, ?, ?, ?, ?, ?, ?, 0, 0, 1)
                """,
                (symbol, side, size, entry_price, leverage, ts, sl, tp, sl, tp, entry_price)
            )
            conn.commit()
            conn.close()
            
            side_es = "LARGO" if side == "LONG" else "CORTO"
            mode_es = "SIMULADO" if self.simulation_mode else "BINGX"
            log_msg = f"Posición abierta {side_es} en {symbol} ({mode_es}) | Cant: {size:.4f} @ ${entry_price:,.2f} | SL: ${sl:,.2f}, TP: ${tp:,.2f} | Margen: {ENTRY_MARGIN_USDT:.2f} USDT, Exposición: {ENTRY_EXPOSURE_USDT:.2f} USDT, Apalancamiento: {leverage}x"
            logger.info(log_msg)
            self.log_to_db("SUCCESS", log_msg)
            return True
        except Exception as e:
            logger.error(f"Error writing position to DB: {e}")
            return False

    def manage_dynamic_exit(
        self,
        pos: Dict[str, Any],
        current_price: float,
        latest_atr: float
    ) -> Optional[Dict[str, Any]]:
        """Updates breakeven/trailing state and returns a close instruction when an exit is hit."""
        side = pos["side"]
        entry_price = float(pos["entry_price"])
        current_sl = pos.get("sl")
        current_tp = pos.get("tp")
        initial_sl = pos.get("initial_sl")
        initial_tp = pos.get("initial_tp")

        if current_sl is None or np.isnan(current_sl):
            current_sl = entry_price - STOP_LOSS_ATR_MULTIPLIER * latest_atr if side == "LONG" else entry_price + STOP_LOSS_ATR_MULTIPLIER * latest_atr
        if current_tp is None or np.isnan(current_tp):
            stop_distance = abs(entry_price - current_sl)
            current_tp = entry_price + TAKE_PROFIT_R_MULTIPLIER * stop_distance if side == "LONG" else entry_price - TAKE_PROFIT_R_MULTIPLIER * stop_distance
        if initial_sl is None or np.isnan(initial_sl):
            initial_sl = current_sl
        if initial_tp is None or np.isnan(initial_tp):
            initial_tp = current_tp

        target_distance = abs(initial_tp - entry_price)
        if target_distance <= 0:
            logger.warning(f"Invalid target distance for {pos['symbol']}; skipping dynamic exit update.")
            return None

        direction = 1 if side == "LONG" else -1
        favorable_progress = direction * (current_price - entry_price) / target_distance
        peak_price = pos.get("peak_price")
        if peak_price is None or np.isnan(peak_price):
            peak_price = entry_price
        peak_price = max(float(peak_price), current_price) if side == "LONG" else min(float(peak_price), current_price)

        breakeven_active = int(pos.get("breakeven_active") or 0)
        trailing_active = int(pos.get("trailing_active") or 0)
        take_profit_active = int(pos.get("take_profit_active") if pos.get("take_profit_active") is not None else 1)
        new_sl = float(current_sl)
        new_tp = float(current_tp)
        state_changed = False

        if favorable_progress >= TRAILING_TRIGGER_PROGRESS:
            trailing_distance = TRAILING_DISTANCE_PROGRESS * target_distance
            trailing_sl = peak_price - trailing_distance if side == "LONG" else peak_price + trailing_distance
            new_sl = max(new_sl, trailing_sl) if side == "LONG" else min(new_sl, trailing_sl)
            if not trailing_active or take_profit_active:
                self.log_to_db("INFO", f"Trailing activado en {pos['symbol']}: TP desactivado y stop dinámico a {TRAILING_DISTANCE_PROGRESS:.0%} de la distancia objetivo.")
            trailing_active = 1
            take_profit_active = 0
            state_changed = True
        elif take_profit_active:
            if side == "LONG" and current_price >= new_tp:
                return {"price": new_tp, "reason": "TAKE_PROFIT"}
            if side == "SHORT" and current_price <= new_tp:
                return {"price": new_tp, "reason": "TAKE_PROFIT"}

        if side == "LONG" and current_price <= new_sl:
            return {"price": new_sl, "reason": "STOP_LOSS" if new_sl <= entry_price else "PROTECTED_STOP"}
        if side == "SHORT" and current_price >= new_sl:
            return {"price": new_sl, "reason": "STOP_LOSS" if new_sl >= entry_price else "PROTECTED_STOP"}

        if state_changed or peak_price != pos.get("peak_price"):
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE positions
                    SET sl = ?, tp = ?, initial_sl = ?, initial_tp = ?, peak_price = ?,
                        breakeven_active = ?, trailing_active = ?, take_profit_active = ?
                    WHERE id = ?
                    """,
                    (new_sl, new_tp, initial_sl, initial_tp, peak_price, breakeven_active, trailing_active, take_profit_active, pos["id"])
                )
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Error updating dynamic exit state: {e}")

        return None

    def close_open_position(self, pos: Dict[str, Any], exit_price: float, reason: str):
        """Closes an open position, realizes PnL, and updates history."""
        symbol = pos["symbol"]
        side = pos["side"]
        size = pos["size"]
        entry_price = pos["entry_price"]
        leverage = pos["leverage"]
        pos_id = pos["id"]
        
        # Calculate closed PnL
        if side == "LONG":
            pnl = (exit_price - entry_price) * size
        else:
            pnl = (entry_price - exit_price) * size
            
        # Reconcile exchange order if live trading
        if not self.simulation_mode:
            # Place closing order on exchange
            order_side = "SELL" if side == "LONG" else "BUY"
            pos_side = "LONG" if side == "LONG" else "SHORT"
            res = self.client.place_order(symbol, order_side, pos_side, "MARKET", size)
            if res["success"]:
                exit_price = res.get("price", exit_price)
                if side == "LONG":
                    pnl = (exit_price - entry_price) * size
                else:
                    pnl = (entry_price - exit_price) * size

        result = "WIN" if pnl >= 0 else "LOSS"
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Trigger 30-minute cooldown on losses
        if result == "LOSS":
            self.set_cooldown(symbol, 30)

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 1. Insert into trades table
            cursor.execute(
                "INSERT INTO trades (symbol, side, size, entry_price, exit_price, leverage, pnl, timestamp, result, exit_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (symbol, side, size, entry_price, exit_price, leverage, pnl, ts, result, reason)
            )
            
            # 2. Delete from positions
            cursor.execute("DELETE FROM positions WHERE id = ?", (pos_id,))
            
            # 3. Update VST balance in DB
            cursor.execute("SELECT value FROM bot_state WHERE key = 'vst_balance'")
            current_bal = float(cursor.fetchone()[0])
            new_bal = current_bal + pnl
            cursor.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES ('vst_balance', ?)", (str(new_bal),))
            
            conn.commit()
            conn.close()
            
            # Record in Kelly sizer database
            self.sizer.record_trade(symbol, side, entry_price, exit_price, pnl)
            
            side_es = "LARGO" if side == "LONG" else "CORTO"
            mode_es = "SIMULADA" if self.simulation_mode else "BINGX"
            reason_labels = {
                "STOP_LOSS": "LÍMITE DE PÉRDIDAS (SL)",
                "TAKE_PROFIT": "TOMA DE GANANCIAS (TP)",
                "PROTECTED_STOP": "STOP PROTEGIDO / TRAILING",
            }
            reason_es = reason_labels.get(reason, reason)
            log_msg = f"Posición {side_es} cerrada en {symbol} ({mode_es}) por {reason_es} a ${exit_price:,.2f}. PnL Realizado: {pnl:+.2f} VST"
            logger.info(log_msg)
            self.log_to_db("SUCCESS", log_msg)
            
        except Exception as e:
            logger.error(f"Error closing position in DB: {e}")

    def run_one_iteration(self):
        """Runs a single execution cycle: reads configs, calculates metrics, makes trades, manages risks."""
        state = self.get_bot_state()
        
        # Check if bot auto trading is turned on by the user
        if not state["running_state"]:
            logger.debug("Execution trader is paused by dashboard. Idle.")
            return

        # 0. Periodic exchange reconciliation every 5 minutes to purge ghost positions
        import time
        current_ts = time.time()
        if not hasattr(self, '_last_sync_time'):
            self._last_sync_time = 0
        if current_ts - self._last_sync_time > 300:  # Every 5 minutes
            self._sync_positions_from_exchange()
            self._last_sync_time = current_ts

        # 1. Periodically update top 80 highest volume crypto pairs (every 1 hour)
        if len(self.symbols_list) == 0 or time.time() - self.last_symbols_update > 3600:
            logger.info("Actualizando la lista de las 80 criptomonedas USDT-M con mayor volumen diario...")
            self.symbols_list = self.client.get_top_volume_coins(TOP_VOLUME_SYMBOL_LIMIT)
            self.last_symbols_update = time.time()

        symbols_to_scan = list(dict.fromkeys(self.symbols_list[:TOP_VOLUME_SYMBOL_LIMIT]))
        open_symbols = self.get_open_position_symbols()
        active_positions_count = self.get_active_positions_count()

        logger.info(f"Escaneando mercado: {len(symbols_to_scan)} criptos top volumen. Posiciones abiertas actuales: {active_positions_count}/{MAX_OPEN_POSITIONS}")
        
        # Loop through symbols to scan sequentially
        for symbol in symbols_to_scan:
            try:
                # Add a tiny delay to respect API rate limits (70 requests is extremely safe for 500 requests/10s limit)
                time.sleep(0.04)
                
                # Fetch public market Klines (doesn't require valid key)
                df = self.client.get_klines(symbol, interval="5m", limit=150)
                if df is None or df.empty:
                    continue

                # Calculate Indicators
                df = calculate_vwap(df)
                df = calculate_atr(df)
                df = calculate_institutional_features(df)
                df = generate_institutional_signals(df)

                # Get latest closed candle (index -2) to prevent repainting issues
                latest_candle = df.iloc[-2]
                current_candle_time = df.index[-2]
                current_price = df['close'].iloc[-1] # Close of index -1 is current active market price

                # 1. Manage active position if open
                open_pos = self.get_open_position(symbol)
                
                if open_pos:
                    # Reconcile database unrealized PnL with current market price
                    side = open_pos["side"]
                    size = open_pos["size"]
                    entry_p = open_pos["entry_price"]
                    sl = open_pos.get("sl")
                    tp = open_pos.get("tp")
                    leverage = open_pos.get("leverage", 10)
                    
                    # Fallback if SL/TP were not stored by an older deployment.
                    if sl is None or np.isnan(sl):
                        sl = entry_p - STOP_LOSS_ATR_MULTIPLIER * latest_candle["atr"] if side == "LONG" else entry_p + STOP_LOSS_ATR_MULTIPLIER * latest_candle["atr"]
                    if tp is None or np.isnan(tp):
                        stop_distance = abs(entry_p - sl)
                        tp = entry_p + TAKE_PROFIT_R_MULTIPLIER * stop_distance if side == "LONG" else entry_p - TAKE_PROFIT_R_MULTIPLIER * stop_distance
                    
                    # Calculate current unrealized PnL
                    if side == "LONG":
                        unrealized_pnl = (current_price - entry_p) * size
                    else:
                        unrealized_pnl = (entry_p - current_price) * size

                    # Update live unrealized PnL in database for Streamlit to pull
                    try:
                        conn = sqlite3.connect(self.db_path)
                        cursor = conn.cursor()
                        cursor.execute("UPDATE positions SET unrealized_pnl = ? WHERE id = ?", (unrealized_pnl, open_pos["id"]))
                        conn.commit()
                        conn.close()
                    except Exception as e:
                        logger.error(f"Error updating positions table unrealized pnl: {e}")

                    exit_signal = self.manage_dynamic_exit(open_pos, current_price, float(latest_candle["atr"]))
                    if exit_signal:
                        self.close_open_position(open_pos, exit_signal["price"], exit_signal["reason"])
                        active_positions_count -= 1
                            
                # 2. Open new position if no active position is open and a signal exists
                else:
                    # Enforce strict maximum of 10 concurrent open positions, one per pair.
                    if active_positions_count >= MAX_OPEN_POSITIONS:
                        continue
                    if symbol in open_symbols:
                        continue
                        
                    signal = latest_candle["signal"]
                    
                    # Only trigger on a new signal candle
                    if signal != 0:
                        # Check cooldown before entry
                        if self.is_in_cooldown(symbol):
                            logger.debug(f"Entrada bloqueada en {symbol}: La moneda esta en periodo de enfriamiento.")
                            continue

                        leverage = ENTRY_LEVERAGE
                        exposure = ENTRY_EXPOSURE_USDT
                        order_qty = exposure / current_price
                        
                        # Precision scaling based on standard assets
                        if "BTC" in symbol:
                            order_qty = round(order_qty, 4)
                        elif "ETH" in symbol:
                            order_qty = round(order_qty, 3)
                        else:
                            order_qty = round(order_qty, 2)
                            
                        if order_qty <= 0:
                            continue

                        # Execute Trade
                        side_tag = "LONG" if signal == 1 else "SHORT"
                        side_es = "LARGO" if side_tag == "LONG" else "CORTO"
                        microstructure = self.get_microstructure_confirmation(symbol, side_tag)
                        if not microstructure["allowed"]:
                            logger.debug(f"Entrada bloqueada en {symbol}: microestructura={microstructure.get('reason')}")
                            continue

                        limit_price = self.calculate_aggressive_limit_price(symbol, side_tag, current_price)
                        logger.info(
                            f"Activando entrada LIMIT IOC {side_es} en {symbol} a ${limit_price:,.2f} | "
                            f"Margen fijo: {ENTRY_MARGIN_USDT:.2f} USDT | Exposición: {ENTRY_EXPOSURE_USDT:.2f} USDT | "
                            f"Apalancamiento {ENTRY_LEVERAGE}x | OBI: {microstructure.get('obi', 0):+.4f} | "
                            f"Spread: {microstructure.get('spread_bps', 0):.2f} bps | "
                            f"Microprice edge: {microstructure.get('microprice_edge_bps', 0):+.2f} bps"
                        )
                        
                        # Place aggressive IOC limit order with 10x leverage.
                        if self.execute_entry_order(symbol, side_tag, order_qty, current_price, leverage, float(latest_candle["atr"])):
                            active_positions_count += 1
                            open_symbols.add(symbol)
                            
            except Exception as e:
                logger.error(f"Error processing symbol {symbol} in scan loop: {e}")

    def start_loop(self):
        """Starts the persistent autonomous trading execution engine thread."""
        logger.info("Iniciando el ciclo de ejecución de Scalper Autónomo...")
        self.log_to_db("INFO", "Ciclo de ejecución de Scalper Autónomo activado.")
        
        while True:
            try:
                self.run_one_iteration()
            except Exception as e:
                logger.error(f"Error in execution cycle iteration: {e}")
                
            # Scalper runs quickly: poll every 15 seconds
            time.sleep(15)

if __name__ == "__main__":
    trader = ExecutionTrader()
    
    # Run once as a check, or start loop
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        logger.info("Executing a single validation cycle iteration...")
        trader.run_one_iteration()
        logger.info("Validation completed successfully.")
    else:
        trader.start_loop()
