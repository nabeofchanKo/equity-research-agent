"""
Tests for src/technical_indicators.py

All tests use synthetic price data so no network or OpenD connection is needed.
"""

import math
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.technical_indicators import (
    _bollinger,
    _ema,
    _macd,
    _rsi,
    _sma,
    _stochastic,
    _support_resistance,
    compute_all,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(closes: list[float], n: int | None = None) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a closing price series."""
    if n is not None:
        # Constant price series of length n
        closes = [100.0] * n
    highs  = [c * 1.01 for c in closes]
    lows   = [c * 0.99 for c in closes]
    opens  = [c * 1.002 for c in closes]
    vols   = [1_000_000] * len(closes)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                          "close": closes, "volume": vols})


def _trending_up(n: int = 250, start: float = 100.0, step: float = 0.5) -> pd.DataFrame:
    closes = [start + i * step for i in range(n)]
    return _make_df(closes)


def _trending_down(n: int = 250, start: float = 200.0, step: float = 0.5) -> pd.DataFrame:
    closes = [start - i * step for i in range(n)]
    return _make_df(closes)


def _flat(n: int = 250, price: float = 100.0) -> pd.DataFrame:
    return _make_df([price] * n)


# ---------------------------------------------------------------------------
# _sma
# ---------------------------------------------------------------------------

class TestSma:
    def test_simple_average(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _sma(s, 3)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[4] == pytest.approx(4.0)

    def test_period_longer_than_series_all_nan(self):
        s = pd.Series([1.0, 2.0])
        result = _sma(s, 5)
        assert result.isna().all()

    def test_constant_series(self):
        s = pd.Series([50.0] * 30)
        result = _sma(s, 20)
        assert result.iloc[-1] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# _ema
# ---------------------------------------------------------------------------

class TestEma:
    def test_converges_on_constant_series(self):
        s = pd.Series([100.0] * 50)
        result = _ema(s, 12)
        assert result.iloc[-1] == pytest.approx(100.0, abs=1e-6)

    def test_rises_on_increasing_series(self):
        s = pd.Series(range(1, 51), dtype=float)
        result = _ema(s, 12)
        assert result.iloc[-1] > result.iloc[20]


# ---------------------------------------------------------------------------
# _rsi
# ---------------------------------------------------------------------------

class TestRsi:
    def test_strongly_trending_up_approaches_100(self):
        closes = pd.Series([100.0 + i for i in range(50)])
        rsi = _rsi(closes, 14)
        assert rsi.iloc[-1] > 90

    def test_strongly_trending_down_approaches_0(self):
        closes = pd.Series([100.0 - i for i in range(50)])
        rsi = _rsi(closes, 14)
        assert rsi.iloc[-1] < 10

    def test_bounds(self):
        closes = pd.Series(np.random.default_rng(0).normal(100, 5, 200))
        rsi = _rsi(closes, 14).dropna()
        assert (rsi >= 0).all() and (rsi <= 100).all()

    def test_flat_series_is_nan_or_neutral(self):
        closes = pd.Series([100.0] * 30)
        rsi = _rsi(closes, 14)
        # All deltas are 0, so RSI is indeterminate (NaN) or exactly 50
        last = rsi.iloc[-1]
        assert pd.isna(last) or last == pytest.approx(50.0, abs=1.0)


# ---------------------------------------------------------------------------
# _macd
# ---------------------------------------------------------------------------

class TestMacd:
    def test_positive_histogram_on_strong_uptrend(self):
        closes = pd.Series([100.0 + i * 2 for i in range(100)])
        macd_line, signal_line, hist = _macd(closes, 12, 26, 9)
        assert hist.iloc[-1] > 0

    def test_negative_histogram_on_strong_downtrend(self):
        closes = pd.Series([300.0 - i * 2 for i in range(100)])
        macd_line, signal_line, hist = _macd(closes, 12, 26, 9)
        assert hist.iloc[-1] < 0

    def test_histogram_equals_macd_minus_signal(self):
        closes = pd.Series(np.random.default_rng(1).normal(100, 3, 100))
        macd_line, signal_line, hist = _macd(closes, 12, 26, 9)
        diff = (macd_line - signal_line - hist).dropna()
        assert (diff.abs() < 1e-10).all()


# ---------------------------------------------------------------------------
# _bollinger
# ---------------------------------------------------------------------------

class TestBollinger:
    def test_upper_above_middle_above_lower(self):
        closes = pd.Series(np.random.default_rng(2).normal(100, 3, 60))
        upper, mid, lower = _bollinger(closes, 20, 2.0)
        valid = upper.dropna()
        assert len(valid) > 0
        assert (upper.dropna() >= mid.dropna()).all()
        assert (mid.dropna() >= lower.dropna()).all()

    def test_constant_series_zero_bandwidth(self):
        closes = pd.Series([100.0] * 40)
        upper, mid, lower = _bollinger(closes, 20, 2.0)
        assert upper.iloc[-1] == pytest.approx(mid.iloc[-1])
        assert lower.iloc[-1] == pytest.approx(mid.iloc[-1])

    def test_std_multiplier_scales_bands(self):
        closes = pd.Series(np.random.default_rng(3).normal(100, 5, 60))
        u1, m1, l1 = _bollinger(closes, 20, 1.0)
        u2, m2, l2 = _bollinger(closes, 20, 2.0)
        # Width with std=2 should be double that with std=1
        w1 = (u1 - l1).dropna()
        w2 = (u2 - l2).dropna()
        assert (w2 - 2 * w1).abs().max() < 1e-8


# ---------------------------------------------------------------------------
# _stochastic
# ---------------------------------------------------------------------------

class TestStochastic:
    def test_bounds(self):
        df = _trending_up(100)
        k, d = _stochastic(df["high"], df["low"], df["close"], 14, 3)
        valid_k = k.dropna()
        assert (valid_k >= 0).all() and (valid_k <= 100).all()

    def test_k_near_100_at_end_of_uptrend(self):
        closes = [100.0 + i * 0.5 for i in range(50)]
        df = _make_df(closes)
        k, _ = _stochastic(df["high"], df["low"], df["close"], 14, 3)
        assert k.iloc[-1] > 80

    def test_k_near_0_at_end_of_downtrend(self):
        closes = [200.0 - i * 0.5 for i in range(50)]
        df = _make_df(closes)
        k, _ = _stochastic(df["high"], df["low"], df["close"], 14, 3)
        assert k.iloc[-1] < 20


# ---------------------------------------------------------------------------
# _support_resistance
# ---------------------------------------------------------------------------

class TestSupportResistance:
    def test_returns_dict_with_required_keys(self):
        df = _trending_up(100)
        sr = _support_resistance(df["high"], df["low"], df["close"])
        assert "support" in sr and "resistance" in sr

    def test_support_below_current_price(self):
        df = _trending_up(100)
        current = float(df["close"].iloc[-1])
        sr = _support_resistance(df["high"], df["low"], df["close"])
        for level in sr["support"]:
            assert level <= current

    def test_resistance_above_current_price(self):
        df = _trending_up(100)
        current = float(df["close"].iloc[-1])
        sr = _support_resistance(df["high"], df["low"], df["close"])
        for level in sr["resistance"]:
            assert level >= current

    def test_short_series_returns_empty_levels(self):
        df = _trending_up(5)
        sr = _support_resistance(df["high"], df["low"], df["close"], window=10)
        assert sr["support"] == [] and sr["resistance"] == []


# ---------------------------------------------------------------------------
# compute_all
# ---------------------------------------------------------------------------

class TestComputeAll:
    def test_returns_all_required_keys(self):
        df = _trending_up(250)
        result = compute_all(df)
        required = {
            "latest_price", "sma", "rsi", "macd",
            "bollinger", "stochastic", "support_resistance",
            "signal_score", "signal_label", "data_points",
        }
        assert required.issubset(result.keys())

    def test_data_points_matches_input(self):
        df = _trending_up(200)
        result = compute_all(df)
        assert result["data_points"] == 200

    def test_latest_price_correct(self):
        closes = [100.0 + i for i in range(100)]
        df = _make_df(closes)
        result = compute_all(df)
        assert result["latest_price"] == pytest.approx(closes[-1], abs=0.01)

    def test_sma_keys_from_config(self):
        df = _trending_up(250)
        result = compute_all(df)
        # Config specifies [20, 50, 200]
        assert set(result["sma"].keys()) == {20, 50, 200}

    def test_sma_none_when_insufficient_data(self):
        # Only 30 rows — SMA200 should be None
        df = _trending_up(30)
        result = compute_all(df)
        assert result["sma"][200] is None
        assert result["sma"][20] is not None

    def test_signal_score_in_valid_range(self):
        for df in [_trending_up(250), _trending_down(250), _flat(250)]:
            result = compute_all(df)
            assert -1.0 <= result["signal_score"] <= 1.0

    def test_uptrend_gives_bullish_signal(self):
        df = _trending_up(250, step=1.0)
        result = compute_all(df)
        assert result["signal_score"] > 0

    def test_downtrend_gives_bearish_signal(self):
        df = _trending_down(250, step=1.0)
        result = compute_all(df)
        assert result["signal_score"] < 0

    def test_signal_label_strong_buy_on_uptrend(self):
        df = _trending_up(250, step=2.0)
        result = compute_all(df)
        assert result["signal_label"] in ("Strong Buy", "Buy")

    def test_signal_label_valid_value(self):
        df = _flat(250)
        result = compute_all(df)
        assert result["signal_label"] in (
            "Strong Buy", "Buy", "Neutral", "Sell", "Strong Sell"
        )

    def test_rsi_value_in_valid_range(self):
        df = _trending_up(100)
        result = compute_all(df)
        rsi_val = result["rsi"]["value"]
        if rsi_val is not None:
            assert 0 <= rsi_val <= 100

    def test_bollinger_upper_above_lower(self):
        df = _trending_up(250)
        result = compute_all(df)
        bb = result["bollinger"]
        if bb["upper"] is not None and bb["lower"] is not None:
            assert bb["upper"] >= bb["lower"]

    def test_bollinger_bandwidth_non_negative(self):
        df = _trending_up(250)
        result = compute_all(df)
        bw = result["bollinger"]["bandwidth"]
        if bw is not None:
            assert bw >= 0

    def test_accepts_column_aliases(self):
        """trade_vol / trade_val / time_key aliases should be accepted."""
        df = _trending_up(100)
        df = df.rename(columns={"volume": "trade_vol"})
        result = compute_all(df)  # must not raise
        assert "latest_price" in result

    def test_raises_on_missing_required_column(self):
        df = _trending_up(100).drop(columns=["close"])
        with pytest.raises(ValueError, match="close"):
            compute_all(df)

    def test_raises_on_single_row_df(self):
        df = _make_df([100.0])
        with pytest.raises(ValueError):
            compute_all(df)

    def test_config_override_via_mock(self):
        """If config overrides rsi_period, it should be reflected in output."""
        custom_cfg = {
            "sma_periods": [10, 20],
            "rsi_period": 7,
            "macd_fast": 6,
            "macd_slow": 13,
            "macd_signal": 5,
            "bollinger_period": 10,
            "bollinger_std": 2,
        }
        df = _trending_up(100)
        with patch("src.technical_indicators._cfg", return_value=custom_cfg):
            result = compute_all(df)
        assert set(result["sma"].keys()) == {10, 20}
        assert result["rsi"]["period"] == 7
        assert result["macd"]["fast"] == 6

    def test_no_nan_in_numeric_output_with_sufficient_data(self):
        """With 250 bars, all indicator values should be non-None."""
        df = _trending_up(250)
        result = compute_all(df)
        assert result["sma"][200] is not None
        assert result["rsi"]["value"] is not None
        assert result["macd"]["macd"] is not None
        assert result["bollinger"]["upper"] is not None
        assert result["stochastic"]["k"] is not None
