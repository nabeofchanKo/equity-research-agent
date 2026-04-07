"""
Technical Indicators Module

Computes SMA, RSI, MACD, Bollinger Bands, Stochastic Oscillator,
support/resistance levels, and an overall signal score from OHLCV data.

Uses pandas and numpy only — no external TA library required.
Periods are read from config/settings.yaml.
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_technical_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    try:
        with open(config_path) as f:
            return yaml.safe_load(f).get("technical", {})
    except Exception as exc:
        logger.warning("Could not load settings.yaml: %s — using defaults", exc)
        return {}


_DEFAULT_CFG = {
    "sma_periods": [20, 50, 200],
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bollinger_period": 20,
    "bollinger_std": 2,
}


def _cfg() -> dict:
    loaded = _load_technical_config()
    return {**_DEFAULT_CFG, **loaded}


# ---------------------------------------------------------------------------
# Column normalisation
# ---------------------------------------------------------------------------

_COL_ALIASES = {
    "trade_vol": "volume",
    "trade_val": "turnover",
    "time_key": "date",
    "Date": "date",
}


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename aliased column names to canonical form."""
    return df.rename(columns={k: v for k, v in _COL_ALIASES.items() if k in df.columns})


# ---------------------------------------------------------------------------
# Individual indicator functions
# ---------------------------------------------------------------------------

def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    # avg_loss == 0 and avg_gain > 0 → pure uptrend → RSI = 100
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), other=100.0)
    return rsi


def _macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger(
    close: pd.Series,
    period: int = 20,
    std_mult: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (upper_band, middle_band, lower_band)."""
    mid = _sma(close, period)
    std = close.rolling(window=period, min_periods=period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower


def _stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """Returns (%K, %D)."""
    lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
    highest_high = high.rolling(window=k_period, min_periods=k_period).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    k = 100 * (close - lowest_low) / denom
    d = k.rolling(window=d_period, min_periods=d_period).mean()
    return k, d


def _support_resistance(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 10,
    n_levels: int = 3,
) -> dict[str, list[float]]:
    """
    Identify support and resistance levels from recent swing highs/lows.

    A swing high is a bar whose high is the highest in a symmetric window.
    A swing low is a bar whose low is the lowest in a symmetric window.
    """
    n = len(close)
    support_prices: list[float] = []
    resistance_prices: list[float] = []

    for i in range(window, n - window):
        lo_window = low.iloc[i - window: i + window + 1]
        hi_window = high.iloc[i - window: i + window + 1]

        if low.iloc[i] == lo_window.min():
            support_prices.append(float(low.iloc[i]))
        if high.iloc[i] == hi_window.max():
            resistance_prices.append(float(high.iloc[i]))

    current = float(close.iloc[-1])

    # Keep the N nearest levels below (support) and above (resistance)
    supports = sorted(
        {round(p, 4) for p in support_prices if p <= current},
        reverse=True,
    )[:n_levels]
    resistances = sorted(
        {round(p, 4) for p in resistance_prices if p >= current},
    )[:n_levels]

    return {"support": supports, "resistance": resistances}


# ---------------------------------------------------------------------------
# Signal scoring
# ---------------------------------------------------------------------------

def _signal_score(
    close: pd.Series,
    sma_values: dict[int, float],
    rsi_val: float,
    macd_val: float,
    macd_signal_val: float,
    bb_upper: float,
    bb_lower: float,
    stoch_k: float,
) -> float:
    """
    Compute a composite signal score in [-1, +1].

    Scoring components (equal weight):
      1. Price vs SMA200  (+0.2 bullish / -0.2 bearish)
      2. Price vs SMA50   (+0.15 / -0.15)
      3. Price vs SMA20   (+0.1 / -0.1)
      4. RSI              (oversold < 30 → +0.2, overbought > 70 → -0.2)
      5. MACD vs signal   (bullish cross → +0.2, bearish → -0.2)
      6. Bollinger        (near lower → +0.075, near upper → -0.075)
      7. Stochastic       (< 20 → +0.075, > 80 → -0.075)
    """
    price = float(close.iloc[-1])
    score = 0.0

    # SMA signals
    sma_weights = {200: 0.20, 50: 0.15, 20: 0.10}
    for period, weight in sma_weights.items():
        sma_val = sma_values.get(period)
        if sma_val is not None and not np.isnan(sma_val):
            score += weight if price > sma_val else -weight

    # RSI
    if not np.isnan(rsi_val):
        if rsi_val < 30:
            score += 0.20
        elif rsi_val > 70:
            score -= 0.20
        # 30–70 is neutral (no contribution)

    # MACD
    if not (np.isnan(macd_val) or np.isnan(macd_signal_val)):
        score += 0.20 if macd_val > macd_signal_val else -0.20

    # Bollinger Bands
    bb_range = bb_upper - bb_lower
    if bb_range > 0 and not np.isnan(bb_upper):
        bb_pos = (price - bb_lower) / bb_range  # 0 = at lower, 1 = at upper
        if bb_pos < 0.2:
            score += 0.075
        elif bb_pos > 0.8:
            score -= 0.075

    # Stochastic
    if not np.isnan(stoch_k):
        if stoch_k < 20:
            score += 0.075
        elif stoch_k > 80:
            score -= 0.075

    return round(max(-1.0, min(1.0, score)), 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_all(df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute all technical indicators for a given OHLCV DataFrame.

    Args:
        df: DataFrame with columns 'open', 'close', 'high', 'low', 'volume'
            (or aliases: 'trade_vol' for volume, 'time_key'/'Date' for date).
            Rows should be in chronological order (oldest first).

    Returns:
        Dictionary with the following keys:

        latest_price : float — most recent closing price
        sma          : {20: float, 50: float, 200: float}
        rsi          : {"value": float, "period": int}
        macd         : {"macd": float, "signal": float, "histogram": float,
                        "fast": int, "slow": int, "signal_period": int}
        bollinger    : {"upper": float, "middle": float, "lower": float,
                        "period": int, "std": float, "bandwidth": float}
        stochastic   : {"k": float, "d": float}
        support_resistance : {"support": [float, ...], "resistance": [float, ...]}
        signal_score : float in [-1, +1] (-1 = strong bearish, +1 = strong bullish)
        signal_label : "Strong Buy" | "Buy" | "Neutral" | "Sell" | "Strong Sell"
        data_points  : int — number of rows used
    """
    df = _normalise_columns(df.copy())

    required = {"open", "close", "high", "low"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {missing}")

    if len(df) < 2:
        raise ValueError("DataFrame must have at least 2 rows")

    cfg = _cfg()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    # ---- SMA ----------------------------------------------------------------
    sma_periods: list[int] = cfg["sma_periods"]
    sma_series = {p: _sma(close, p) for p in sma_periods}
    sma_values: dict[int, float | None] = {}
    for p, series in sma_series.items():
        last = series.iloc[-1]
        sma_values[p] = None if pd.isna(last) else round(float(last), 4)

    # ---- RSI ----------------------------------------------------------------
    rsi_period: int = cfg["rsi_period"]
    rsi_series = _rsi(close, rsi_period)
    rsi_last = rsi_series.iloc[-1]
    rsi_val = float(rsi_last) if not pd.isna(rsi_last) else float("nan")

    # ---- MACD ---------------------------------------------------------------
    macd_fast: int = cfg["macd_fast"]
    macd_slow: int = cfg["macd_slow"]
    macd_signal_period: int = cfg["macd_signal"]
    macd_line, macd_signal_line, macd_hist = _macd(close, macd_fast, macd_slow, macd_signal_period)

    def _last(s: pd.Series) -> float | None:
        v = s.iloc[-1]
        return None if pd.isna(v) else round(float(v), 6)

    # ---- Bollinger Bands ----------------------------------------------------
    bb_period: int = cfg["bollinger_period"]
    bb_std: float = float(cfg["bollinger_std"])
    bb_upper_s, bb_mid_s, bb_lower_s = _bollinger(close, bb_period, bb_std)
    bb_upper_v = _last(bb_upper_s)
    bb_mid_v = _last(bb_mid_s)
    bb_lower_v = _last(bb_lower_s)
    bb_bw = (
        round((bb_upper_v - bb_lower_v) / bb_mid_v, 4)
        if (bb_upper_v is not None and bb_lower_v is not None and bb_mid_v)
        else None
    )

    # ---- Stochastic Oscillator ----------------------------------------------
    stoch_k_s, stoch_d_s = _stochastic(high, low, close)
    stoch_k_v = _last(stoch_k_s)
    stoch_d_v = _last(stoch_d_s)

    # ---- Support / Resistance -----------------------------------------------
    sr = _support_resistance(high, low, close)

    # ---- Signal Score -------------------------------------------------------
    score = _signal_score(
        close=close,
        sma_values={p: (v if v is not None else float("nan")) for p, v in sma_values.items()},
        rsi_val=rsi_val if not np.isnan(rsi_val) else float("nan"),
        macd_val=float(macd_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else float("nan"),
        macd_signal_val=float(macd_signal_line.iloc[-1]) if not pd.isna(macd_signal_line.iloc[-1]) else float("nan"),
        bb_upper=bb_upper_v if bb_upper_v is not None else float("nan"),
        bb_lower=bb_lower_v if bb_lower_v is not None else float("nan"),
        stoch_k=stoch_k_v if stoch_k_v is not None else float("nan"),
    )

    if score >= 0.5:
        label = "Strong Buy"
    elif score >= 0.15:
        label = "Buy"
    elif score <= -0.5:
        label = "Strong Sell"
    elif score <= -0.15:
        label = "Sell"
    else:
        label = "Neutral"

    return {
        "latest_price": round(float(close.iloc[-1]), 4),
        "sma": sma_values,
        "rsi": {
            "value": round(rsi_val, 2) if not np.isnan(rsi_val) else None,
            "period": rsi_period,
        },
        "macd": {
            "macd": _last(macd_line),
            "signal": _last(macd_signal_line),
            "histogram": _last(macd_hist),
            "fast": macd_fast,
            "slow": macd_slow,
            "signal_period": macd_signal_period,
        },
        "bollinger": {
            "upper": bb_upper_v,
            "middle": bb_mid_v,
            "lower": bb_lower_v,
            "period": bb_period,
            "std": bb_std,
            "bandwidth": bb_bw,
        },
        "stochastic": {
            "k": stoch_k_v,
            "d": stoch_d_v,
        },
        "support_resistance": sr,
        "signal_score": score,
        "signal_label": label,
        "data_points": len(df),
    }
