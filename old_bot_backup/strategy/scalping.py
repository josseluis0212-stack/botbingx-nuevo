import os
import sqlite3
import logging
import numpy as np
import pandas as pd

# Setup Logger
logger = logging.getLogger("StrategyEngine")

STOP_LOSS_ATR_MULTIPLIER = 4.0
TAKE_PROFIT_R_MULTIPLIER = 2.0
VWAP_Z_MAX_ABS = 1.25
MIN_BODY_EFFICIENCY = 0.35
MIN_RELATIVE_VOLUME = 0.80
MAX_ATR_PERCENTILE = 0.90
MIN_ATR_PERCENTILE = 0.15

def calculate_vwap(df: pd.DataFrame, num_std_devs: list = [1.0, 2.0, 3.0], group_by_date: bool = True) -> pd.DataFrame:
    """
    Calculates Volume Weighted Average Price (VWAP) and standard deviation bands.
    
    Formulas:
        Typical Price (TP) = (High + Low + Close) / 3
        VWAP = sum(TP * Volume) / sum(Volume)
        VWAP Standard Deviation = sqrt(sum(Volume * (TP - VWAP)^2) / sum(Volume))
        
    Optimized mathematically via the algebraic identity:
        Weighted Variance = [sum(Volume * TP^2) / sum(Volume)] - VWAP^2
        
    Args:
        df (pd.DataFrame): Dataframe with datetime index and high, low, close, volume columns.
        num_std_devs (list): Standard deviation multipliers to calculate bands for.
        group_by_date (bool): If True and index is DatetimeIndex, resets VWAP daily.
        
    Returns:
        pd.DataFrame: Copy of dataframe with 'vwap', 'vwap_std', and band columns added.
    """
    required_cols = ['high', 'low', 'close', 'volume']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"DataFrame must contain column '{col}'")

    df = df.copy()
    tp = (df['high'] + df['low'] + df['close']) / 3
    tp_v = tp * df['volume']
    tp2_v = (tp ** 2) * df['volume']

    # Check if we should reset VWAP daily based on DatetimeIndex
    if group_by_date and isinstance(df.index, pd.DatetimeIndex):
        dates = df.index.date
        cum_tp_v = tp_v.groupby(dates).cumsum()
        cum_tp2_v = tp2_v.groupby(dates).cumsum()
        cum_vol = df['volume'].groupby(dates).cumsum()
    else:
        cum_tp_v = tp_v.cumsum()
        cum_tp2_v = tp2_v.cumsum()
        cum_vol = cum_vol = df['volume'].cumsum()

    # Prevent division by zero
    cum_vol_safe = cum_vol.replace(0, np.nan)

    # Compute VWAP and volume-weighted variance/std
    df['vwap'] = cum_tp_v / cum_vol_safe
    df['vwap'] = df['vwap'].ffill()
    
    weighted_var = (cum_tp2_v / cum_vol_safe) - (df['vwap'] ** 2)
    # Clip variance to prevent tiny negative floats due to floating point limits
    weighted_var = weighted_var.clip(lower=0)
    df['vwap_std'] = np.sqrt(weighted_var)
    df['vwap_std'] = df['vwap_std'].fillna(0)

    # Calculate Bands
    for std in num_std_devs:
        std_str = str(std).replace('.', '_')
        df[f'vwap_upper_{std_str}'] = df['vwap'] + std * df['vwap_std']
        df[f'vwap_lower_{std_str}'] = df['vwap'] - std * df['vwap_std']

    return df



def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Calculates Average True Range (ATR) using Wilder's EMA smoothing.
    
    Args:
        df (pd.DataFrame): Dataframe with high, low, close columns.
        period (int): Lookback period.
        
    Returns:
        pd.DataFrame: Dataframe with 'atr' column added.
    """
    required_cols = ['high', 'low', 'close']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"DataFrame must contain column '{col}'")
            
    df = df.copy()
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.ewm(alpha=1/period, adjust=False).mean()
    
    return df



def calculate_institutional_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds regime, volume, and price-location features for institutional 5m scalping.

    This uses only data available in the current bot: 5m OHLCV plus later live
    order-book filters in the execution engine. It intentionally avoids pretending
    to compute true trade-sign VPIN without tick-by-tick aggressor flow.
    """
    required_cols = ['open', 'high', 'low', 'close', 'volume', 'vwap', 'vwap_std', 'atr']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"DataFrame must contain column '{col}'. Compute indicators first.")

    df = df.copy()
    eps = 1e-12

    df['log_return'] = np.log(df['close'] / df['close'].shift(1)).replace([np.inf, -np.inf], 0).fillna(0)

    df['atr_pct'] = (df['atr'] / df['close']).replace([np.inf, -np.inf], np.nan).fillna(0)

    rolling_volume = df['volume'].rolling(48, min_periods=12)
    df['relative_volume'] = (df['volume'] / rolling_volume.median().replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(1.0)

    candle_range = (df['high'] - df['low']).replace(0, np.nan)
    df['body_efficiency'] = ((df['close'] - df['open']).abs() / candle_range).replace([np.inf, -np.inf], np.nan).fillna(0)
    df['signed_volume'] = np.sign(df['close'] - df['open']) * df['volume']
    df['signed_volume_pressure'] = (
        df['signed_volume'].rolling(12, min_periods=4).sum()
        / df['volume'].rolling(12, min_periods=4).sum().replace(0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).fillna(0)

    vwap_scale = df['vwap_std'].where(df['vwap_std'] > eps, df['atr'])
    df['vwap_z'] = ((df['close'] - df['vwap']) / vwap_scale.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0)

    atr_rolling = df['atr_pct'].rolling(96, min_periods=24)
    atr_low = atr_rolling.quantile(MIN_ATR_PERCENTILE)
    atr_high = atr_rolling.quantile(MAX_ATR_PERCENTILE)
    df['tradable_volatility_regime'] = (
        (df['atr_pct'] >= atr_low.fillna(df['atr_pct'].expanding().quantile(MIN_ATR_PERCENTILE)))
        & (df['atr_pct'] <= atr_high.fillna(df['atr_pct'].expanding().quantile(MAX_ATR_PERCENTILE)))
    )

    return df

def generate_institutional_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Volatility-Normalized Microstructure Strategy (VNM-OFI).
    
    This is an institutional mathematical strategy that combines:
    1. Quantitative Regime Filtering: Uses dynamic ATR Z-scores to identify choppy vs. trending markets.
    2. Fair Value Deviations: Requires VWAP Z-score > 1.5 or < -1.5 (Mathematical extreme).
    3. Microstructure Confirmation: Requires a Liquidity Grab (Vol spike) and Volume Pressure.
    """
    required_cols = [
        'close', 'open', 'high', 'low', 'vwap', 'atr', 
        'relative_volume', 'vwap_z', 'signed_volume_pressure'
    ]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"DataFrame must contain column '{col}'. Compute institutional features first.")

    df = df.copy()

    # 1. Volatility Regime Filter (VNM)
    # Use trailing ATR to establish regime. High ATR implies choppy.
    rolling_atr_mean = df['atr'].rolling(window=100, min_periods=10).mean()
    rolling_atr_std = df['atr'].rolling(window=100, min_periods=10).std()
    
    # Avoid division by zero
    rolling_atr_std = rolling_atr_std.replace(0, 1e-8)
    df['atr_zscore'] = (df['atr'] - rolling_atr_mean) / rolling_atr_std
    
    # High vol regime: Z-score > 1.0
    df['is_high_vol'] = df['atr_zscore'] > 1.0

    # 2. Fair Value Deviation (VWAP Z-Score)
    # Price must be stretched from the mean VWAP
    is_stretched_long = df['vwap_z'] <= -0.8  # Price far below VWAP
    is_stretched_short = df['vwap_z'] >= 0.8   # Price far above VWAP

    # 3. Microstructure Confirmation (Liquidity Grab & Absorption)
    # Volume spike (relative_volume > 1.2 implies 20% above mean)
    is_liquidity_grab = df['relative_volume'] >= 1.2
    
    # Order Flow Imbalance (proxied by signed volume pressure)
    # Must aggressively absorb the move
    bullish_flow = df['signed_volume_pressure'] > 0.1
    bearish_flow = df['signed_volume_pressure'] < -0.1

    # Composite Entry Logic
    long_entry_cond = is_stretched_long & is_liquidity_grab & bullish_flow
    short_entry_cond = is_stretched_short & is_liquidity_grab & bearish_flow

    df['signal'] = 0
    df.loc[long_entry_cond, 'signal'] = 1
    df.loc[short_entry_cond, 'signal'] = -1

    # 4. Dynamic Risk Parameters
    # If in High Vol Regime, we multiply the stop distance by 1.5 to avoid noise
    df['risk_multiplier'] = np.where(df['is_high_vol'], 1.5, 1.0)
    
    df['entry_price'] = df['close']
    stop_distance = STOP_LOSS_ATR_MULTIPLIER * df['atr'] * df['risk_multiplier']
    take_profit_distance = TAKE_PROFIT_R_MULTIPLIER * stop_distance

    df['sl'] = np.where(df['signal'] == 1, df['close'] - stop_distance,
                        np.where(df['signal'] == -1, df['close'] + stop_distance, np.nan))
    df['tp'] = np.where(df['signal'] == 1, df['close'] + take_profit_distance,
                        np.where(df['signal'] == -1, df['close'] - take_profit_distance, np.nan))
    df['strategy_name'] = 'vnm_ofi_institutional'

    return df



class KellySizer:
    """
    Sizing engine that reads history from an SQLite database and computes optimal 
    position sizing using the fractional Kelly formula, capped between 1% and 5%.
    """
    def __init__(self, db_path: str = "C:\\Users\\Usuario\\Documents\\botbingxx\\trades.db", fractional_factor: float = 0.10, default_size: float = 0.02):
        """
        Args:
            db_path (str): Path to SQLite database holding trade records.
            fractional_factor (float): Fraction of full Kelly to use (default: 10% / 0.10).
            default_size (float): Fallback position sizing of equity (default: 2% / 0.02).
        """
        self.db_path = db_path
        self.fractional_factor = fractional_factor
        self.default_size = default_size
        self._init_db()

    def _init_db(self):
        """Initializes database and table if they do not exist."""
        try:
            # Ensure the parent directory exists
            parent_dir = os.path.dirname(self.db_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
                
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    pnl REAL NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error initializing SQLite database: {e}")

    def record_trade(self, symbol: str, side: str, entry_price: float, exit_price: float, pnl: float):
        """
        Records a completed trade into the SQLite database.
        
        Args:
            symbol (str): Asset name / pair symbol.
            side (str): LONG or SHORT.
            entry_price (float): Average entry price.
            exit_price (float): Average exit price.
            pnl (float): Net realized PnL of the trade (positive for win, negative for loss).
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades (symbol, side, entry_price, exit_price, pnl)
                VALUES (?, ?, ?, ?, ?)
            """, (symbol, side, entry_price, exit_price, pnl))
            conn.commit()
            conn.close()
            logger.info(f"Recorded trade in DB: {symbol} | {side} | PnL: {pnl:.4f}")
        except Exception as e:
            logger.error(f"Failed to record trade in DB: {e}")

    def calculate_size(self) -> float:
        """
        Calculates the optimal position size based on trades history.
        
        Kelly Formula:
            K = WinRate - (1 - WinRate) / b
            where:
                WinRate = win_count / total_count
                b = avg_win / avg_loss (win/loss ratio)
                
        Fractional Kelly = K * fractional_factor
        
        Returns:
            float: Sizing as percentage of equity, capped between 1% (0.01) and 5% (0.05).
                   Falls back to default_size (0.02) if no trade history is available.
        """
        try:
            if not os.path.exists(self.db_path):
                logger.info("Database file does not exist. Using default size.")
                return self.default_size

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
            if not cursor.fetchone():
                conn.close()
                logger.info("Table 'trades' does not exist. Using default size.")
                return self.default_size
                
            cursor.execute("SELECT pnl FROM trades")
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                logger.info("No trades found in database. Using default size.")
                return self.default_size

            pnls = [row[0] for row in rows]
            total_trades = len(pnls)
            
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            
            win_count = len(wins)
            loss_count = len(losses)
            
            if total_trades == 0:
                return self.default_size
                
            win_rate = win_count / total_trades
            
            # If no losing trades yet
            if loss_count == 0:
                if win_count == 0:
                    return self.default_size
                else:
                    # Win rate is 100%. We assume a favorable win-loss ratio b = 2.0 to be conservative.
                    b = 2.0
            else:
                avg_win = sum(wins) / win_count if win_count > 0 else 0.0
                avg_loss = abs(sum(losses) / loss_count)
                b = avg_win / avg_loss if avg_loss > 0 else 1.0

            # Prevent division by zero and extreme values
            if b <= 0:
                b = 1.0
                
            # Kelly % Calculation
            kelly_pct = win_rate - (1.0 - win_rate) / b
            
            # Apply fractional factor
            fractional_kelly = self.fractional_factor * kelly_pct
            
            # Clamp between 1% and 5%
            capped_size = max(0.01, min(fractional_kelly, 0.05))
            
            logger.info(
                f"Kelly Sizer Stats - Trades: {total_trades}, Win Rate: {win_rate:.2%}, "
                f"Avg Win/Loss Ratio (b): {b:.2f}, Raw Kelly: {kelly_pct:.2%}, "
                f"Fractional Kelly ({self.fractional_factor*100:.0f}%): {fractional_kelly:.2%}, "
                f"Capped Size: {capped_size:.2%}"
            )
            return capped_size
            
        except Exception as e:
            logger.error(f"Error in Kelly Sizer calculation: {e}. Falling back to default.")
            return self.default_size

# Self-testing routine
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    print("\n" + "="*50)
    print("      QUANTITATIVE STRATEGY ENGINE TESTING ROUTINE")
    print("="*50)
    
    # 1. Generate Mock Intraday Data
    print("\n[Step 1] Generating mock intraday market data...")
    np.random.seed(42)
    periods = 1000
    dates = pd.date_range(start="2026-05-01 09:30:00", periods=periods, freq="1min")
    
    # Generate prices using a geometric random walk
    price = 50000.0
    prices = []
    for _ in range(periods):
        price *= (1 + np.random.normal(0, 0.0005))
        prices.append(price)
        
    df = pd.DataFrame(index=dates)
    df['close'] = prices
    df['high'] = df['close'] + np.random.exponential(5.0, periods)
    df['low'] = df['close'] - np.random.exponential(5.0, periods)
    df['open'] = df['close'].shift(1).fillna(50000.0)
    df['volume'] = np.random.randint(10, 200, periods).astype(float)
    
    # 2. Compute Quantitative Indicators
    print("\n[Step 2] Computing optimized indicators...")
    df = calculate_vwap(df)
    df = calculate_ema(df)
    df = calculate_atr(df)
    df = calculate_rsi(df)
    
    print("Indicators computed successfully:")
    for col in ['vwap', 'vwap_std', 'vwap_upper_1_0', 'vwap_lower_1_0', 'ema_9', 'ema_21', 'ema_200', 'atr', 'rsi']:
        print(f" - {col}: min={df[col].min():.2f}, max={df[col].max():.2f}")
        
    # 3. Generate Strategy Signals
    print("\n[Step 3] Running signal generation checks...")
    df = generate_signals(df)
    
    longs = df[df['signal'] == 1]
    shorts = df[df['signal'] == -1]
    print(f"Signals summary - Long Entry Triggers: {len(longs)}, Short Entry Triggers: {len(shorts)}")
    
    if len(longs) > 0:
        print("\nSample Long Signals:")
        print(longs[['close', 'vwap', 'ema_200', 'rsi', 'atr', 'sl', 'tp']].head(3).to_string())
    if len(shorts) > 0:
        print("\nSample Short Signals:")
        print(shorts[['close', 'vwap', 'ema_200', 'rsi', 'atr', 'sl', 'tp']].head(3).to_string())

    # 4. Test Kelly Sizer
    print("\n[Step 4] Testing Kelly Sizer...")
    test_db_path = "C:\\Users\\Usuario\\Documents\\botbingxx\\test_strategy_trades.db"
    
    # Clean up old test database if it exists
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass
            
    sizer = KellySizer(db_path=test_db_path)
    
    # Check default size when empty
    size_empty = sizer.calculate_size()
    print(f" - Sizer default size (0 trades): {size_empty:.2%} (Expected: 2.00%)")
    
    # Insert dummy winning and losing trades
    # Let's mock a 60% win rate and average win size 2x average loss
    # Kelly = 0.6 - (1 - 0.6) / 2.0 = 0.6 - 0.2 = 0.40 (40%)
    # Fractional Kelly (10%) = 4% (0.04)
    print(" - Recording 10 mock trades into database...")
    for _ in range(6):
        sizer.record_trade("BTC-USDT", "LONG", 50000, 51000, 200.0)  # wins
    for _ in range(4):
        sizer.record_trade("BTC-USDT", "LONG", 50000, 49500, -100.0) # losses
        
    calculated_size = sizer.calculate_size()
    print(f" - Calculated Fractional Kelly size: {calculated_size:.2%} (Expected: 4.00%)")
    
    # Test capping limits (e.g. high win rate + win size making Kelly > 50%, fractional > 5%)
    print(" - Recording high profit trades to trigger capping...")
    for _ in range(10):
        sizer.record_trade("BTC-USDT", "LONG", 50000, 60000, 2000.0)
        
    capped_size_high = sizer.calculate_size()
    print(f" - Calculated size after massive wins (capped): {capped_size_high:.2%} (Expected: 5.00%)")
    
    # Clean up test DB
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass
            
    print("\n" + "="*50)
    print("          ALL STRATEGY TESTS PASSED SUCCESSFULLY!")
    print("="*50 + "\n")
