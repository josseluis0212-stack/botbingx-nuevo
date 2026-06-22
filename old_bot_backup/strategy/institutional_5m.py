import logging
import os
import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger("Institutional5M")


@dataclass(frozen=True)
class Institutional5MConfig:
    stop_loss_atr_multiplier: float = 4.0
    take_profit_r_multiplier: float = 2.0
    min_relative_volume: float = 0.80
    min_body_efficiency: float = 0.35
    max_abs_vwap_z: float = 1.25
    min_atr_percentile: float = 0.15
    max_atr_percentile: float = 0.90
    volume_window: int = 48
    signed_flow_window: int = 12
    volatility_window: int = 96
    ema_fast: int = 9
    ema_slow: int = 21
    ema_regime: int = 200
    regime_slope_lookback: int = 12


DEFAULT_CONFIG = Institutional5MConfig()


def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    for col in columns:
        if col not in df.columns:
            raise ValueError(f"DataFrame must contain column '{col}'.")


def calculate_vwap(
    df: pd.DataFrame,
    num_std_devs: list[float] | None = None,
    group_by_date: bool = True
) -> pd.DataFrame:
    """Calculates session VWAP and volume-weighted standard deviation bands."""
    if num_std_devs is None:
        num_std_devs = [1.0, 2.0, 3.0]

    _require_columns(df, ["high", "low", "close", "volume"])
    df = df.copy()

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_volume = typical_price * df["volume"]
    tp2_volume = (typical_price ** 2) * df["volume"]

    if group_by_date and isinstance(df.index, pd.DatetimeIndex):
        dates = df.index.date
        cum_tp_volume = tp_volume.groupby(dates).cumsum()
        cum_tp2_volume = tp2_volume.groupby(dates).cumsum()
        cum_volume = df["volume"].groupby(dates).cumsum()
    else:
        cum_tp_volume = tp_volume.cumsum()
        cum_tp2_volume = tp2_volume.cumsum()
        cum_volume = df["volume"].cumsum()

    safe_volume = cum_volume.replace(0, np.nan)
    df["vwap"] = (cum_tp_volume / safe_volume).ffill()
    weighted_var = ((cum_tp2_volume / safe_volume) - (df["vwap"] ** 2)).clip(lower=0)
    df["vwap_std"] = np.sqrt(weighted_var).fillna(0)

    for std in num_std_devs:
        suffix = str(std).replace(".", "_")
        df[f"vwap_upper_{suffix}"] = df["vwap"] + std * df["vwap_std"]
        df[f"vwap_lower_{suffix}"] = df["vwap"] - std * df["vwap_std"]

    return df


def calculate_ema(df: pd.DataFrame, config: Institutional5MConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    """Calculates fast, slow, and regime EMAs."""
    _require_columns(df, ["close"])
    df = df.copy()
    for period in [config.ema_fast, config.ema_slow, config.ema_regime]:
        df[f"ema_{period}"] = df["close"].ewm(span=period, adjust=False).mean()
    return df


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Calculates ATR using Wilder-style exponential smoothing."""
    _require_columns(df, ["high", "low", "close"])
    df = df.copy()

    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = true_range.ewm(alpha=1 / period, adjust=False).mean()
    return df


def calculate_features(
    df: pd.DataFrame,
    config: Institutional5MConfig = DEFAULT_CONFIG
) -> pd.DataFrame:
    """
    Computes institutional 5m features from OHLCV.

    Live order-book features are intentionally handled in the execution engine,
    because stale book data is worse than no book data for adverse-selection risk.
    """
    regime_col = f"ema_{config.ema_regime}"
    fast_col = f"ema_{config.ema_fast}"
    slow_col = f"ema_{config.ema_slow}"
    _require_columns(
        df,
        [
            "open", "high", "low", "close", "volume", "vwap", "vwap_std",
            fast_col, slow_col, regime_col, "atr"
        ],
    )

    df = df.copy()
    eps = 1e-12

    df["log_return"] = np.log(df["close"] / df["close"].shift(1)).replace([np.inf, -np.inf], 0).fillna(0)
    df["ema_regime_slope"] = df[regime_col].pct_change(config.regime_slope_lookback).replace([np.inf, -np.inf], 0).fillna(0)
    df["atr_pct"] = (df["atr"] / df["close"]).replace([np.inf, -np.inf], np.nan).fillna(0)

    rolling_volume = df["volume"].rolling(config.volume_window, min_periods=max(12, config.volume_window // 4))
    df["relative_volume"] = (
        df["volume"] / rolling_volume.median().replace(0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).fillna(1.0)

    candle_range = (df["high"] - df["low"]).replace(0, np.nan)
    df["body_efficiency"] = (
        (df["close"] - df["open"]).abs() / candle_range
    ).replace([np.inf, -np.inf], np.nan).fillna(0)

    df["signed_volume"] = np.sign(df["close"] - df["open"]) * df["volume"]
    df["signed_volume_pressure"] = (
        df["signed_volume"].rolling(config.signed_flow_window, min_periods=4).sum()
        / df["volume"].rolling(config.signed_flow_window, min_periods=4).sum().replace(0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).fillna(0)

    vwap_scale = df["vwap_std"].where(df["vwap_std"] > eps, df["atr"])
    df["vwap_z"] = (
        (df["close"] - df["vwap"]) / vwap_scale.replace(0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).fillna(0)

    atr_rolling = df["atr_pct"].rolling(config.volatility_window, min_periods=max(24, config.volatility_window // 4))
    atr_low = atr_rolling.quantile(config.min_atr_percentile)
    atr_high = atr_rolling.quantile(config.max_atr_percentile)
    fallback_low = df["atr_pct"].expanding().quantile(config.min_atr_percentile)
    fallback_high = df["atr_pct"].expanding().quantile(config.max_atr_percentile)
    df["tradable_volatility_regime"] = (
        (df["atr_pct"] >= atr_low.fillna(fallback_low))
        & (df["atr_pct"] <= atr_high.fillna(fallback_high))
    )

    df["institutional_regime"] = np.select(
        [
            (df["close"] > df[regime_col]) & (df[fast_col] > df[slow_col]) & (df["ema_regime_slope"] >= -0.0005),
            (df["close"] < df[regime_col]) & (df[fast_col] < df[slow_col]) & (df["ema_regime_slope"] <= 0.0005),
        ],
        ["trend_up", "trend_down"],
        default="neutral",
    )

    return df


def generate_signals(
    df: pd.DataFrame,
    config: Institutional5MConfig = DEFAULT_CONFIG
) -> pd.DataFrame:
    """
    Generates the institutional scalping signal.

    Contract:
    - signal: 1 long, -1 short, 0 no trade
    - entry_price/sl/tp: compatible with the execution engine
    """
    _require_columns(
        df,
        [
            "open", "high", "low", "close", "vwap", "atr", "relative_volume",
            "body_efficiency", "signed_volume_pressure", "vwap_z",
            "tradable_volatility_regime", "institutional_regime"
        ],
    )

    df = df.copy()

    quality_gate = (
        df["tradable_volatility_regime"]
        & (df["relative_volume"] >= config.min_relative_volume)
        & (df["body_efficiency"] >= config.min_body_efficiency)
        & (df["vwap_z"].abs() <= config.max_abs_vwap_z)
    )

    long_setup = (
        quality_gate
        & (df["institutional_regime"] == "trend_up")
        & (df["low"] <= df["vwap"])
        & (df["close"] > df["vwap"])
        & (df["close"] > df["open"])
        & (df["signed_volume_pressure"] > 0)
    )
    short_setup = (
        quality_gate
        & (df["institutional_regime"] == "trend_down")
        & (df["high"] >= df["vwap"])
        & (df["close"] < df["vwap"])
        & (df["close"] < df["open"])
        & (df["signed_volume_pressure"] < 0)
    )

    df["signal"] = 0
    df.loc[long_setup, "signal"] = 1
    df.loc[short_setup, "signal"] = -1

    df["entry_price"] = df["close"]
    stop_distance = config.stop_loss_atr_multiplier * df["atr"]
    take_distance = config.take_profit_r_multiplier * stop_distance
    df["sl"] = np.where(
        df["signal"] == 1,
        df["close"] - stop_distance,
        np.where(df["signal"] == -1, df["close"] + stop_distance, np.nan),
    )
    df["tp"] = np.where(
        df["signal"] == 1,
        df["close"] + take_distance,
        np.where(df["signal"] == -1, df["close"] - take_distance, np.nan),
    )
    df["strategy_name"] = "institutional_5m_microstructure_scalper"

    return df


def build_signal_frame(
    df: pd.DataFrame,
    config: Institutional5MConfig = DEFAULT_CONFIG
) -> pd.DataFrame:
    """Full strategy pipeline from raw OHLCV to executable signal frame."""
    df = calculate_vwap(df)
    df = calculate_ema(df, config)
    df = calculate_atr(df)
    df = calculate_features(df, config)
    return generate_signals(df, config)


class TradeHistoryRecorder:
    """Minimal trade recorder used by the execution engine for post-trade research."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        try:
            parent_dir = os.path.dirname(self.db_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    pnl REAL NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error(f"Error initializing strategy trade history: {exc}")

    def record_trade(self, symbol: str, side: str, entry_price: float, exit_price: float, pnl: float) -> None:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO strategy_trade_history (symbol, side, entry_price, exit_price, pnl)
                VALUES (?, ?, ?, ?, ?)
                """,
                (symbol, side, entry_price, exit_price, pnl),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error(f"Error recording strategy trade history: {exc}")
