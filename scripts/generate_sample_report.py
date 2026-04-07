"""
Generate a sample HTML report with realistic mock data for Tencent (HK.00700).
Saves to outputs/SAMPLE_HK_00700_report.html.

Usage:
    python scripts/generate_sample_report.py
    python -m scripts.generate_sample_report
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

# ── path setup ────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.report_generator import generate_report
from src.technical_indicators import compute_all
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Realistic mock data for HK.00700 (Tencent) circa early 2025
# ─────────────────────────────────────────────────────────────────────────────

def _make_kline(n: int = 180) -> list[dict]:
    """Synthesise realistic 180-day daily K-line data centred around 385 HKD."""
    rng = np.random.default_rng(42)
    # Random walk with slight upward drift
    log_returns = rng.normal(0.0008, 0.018, n)
    closes = [385.0]
    for lr in log_returns[1:]:
        closes.append(round(closes[-1] * np.exp(lr), 2))

    today = date.today()
    records = []
    for i, close in enumerate(closes):
        day = today - timedelta(days=n - 1 - i)
        # Skip rough weekends (not perfect but good for mock)
        hi = round(close * (1 + abs(rng.normal(0, 0.008))), 2)
        lo = round(close * (1 - abs(rng.normal(0, 0.008))), 2)
        op = round(lo + rng.random() * (hi - lo), 2)
        vol = int(abs(rng.normal(12_000_000, 3_000_000)))
        records.append({
            "time_key": day.strftime("%Y-%m-%d 00:00:00"),
            "open":     op,
            "high":     hi,
            "low":      lo,
            "close":    close,
            "volume":   vol,
            "turnover": int(vol * close),
        })
    return records


def _mock_snapshot(last_price: float) -> dict:
    return {
        "ticker":         "HK.00700",
        "name":           "Tencent Holdings Limited",
        "last_price":     last_price,
        "change_val":     4.8,
        "change_rate":    1.26,
        "volume":         12_450_000,
        "turnover":       4_780_000_000,
        "market_cap":     3_700_000_000_000,
        "pe_ratio":       19.2,
        "pb_ratio":       3.3,
        "52w_high":       432.0,
        "52w_low":        268.0,
        "dividend_yield": 0.0055,
    }


def _mock_fundamentals() -> dict:
    return {
        "ticker": "HK.00700", "yf_ticker": "0700.HK",
        "name": "Tencent Holdings Limited",
        "sector": "Technology",
        "industry": "Internet Content & Information",
        "market_cap": 3_700_000_000_000,
        "currency": "HKD",
        "current_price": 385.4,
        "pe_ratio": 19.2,
        "forward_pe": 15.8,
        "pb_ratio": 3.3,
        "ps_ratio": 4.5,
        "roe": 0.228,
        "roa": 0.112,
        "eps_ttm": 20.08,
        "eps_forward": 24.40,
        "revenue_ttm": 634_000_000_000,
        "net_income_ttm": 119_000_000_000,
        "profit_margin": 0.188,
        "dividend_yield": 0.0055,
        "dividend_rate": 2.12,
        "beta": 0.84,
        "52w_high": 432.0,
        "52w_low": 268.0,
        "shares_outstanding": 9_610_000_000,
        "book_value": 116.8,
        "debt_to_equity": 27.4,
        "current_ratio": 1.62,
        "quick_ratio": 1.54,
        "gross_margin": 0.482,
        "operating_margin": 0.234,
        "ebitda": 189_000_000_000,
        "enterprise_value": 3_580_000_000_000,
        "ev_to_ebitda": 18.9,
        "ev_to_revenue": 5.65,
        "analyst_target": 458.0,
        "recommendation": "buy",
    }


def _mock_earnings() -> dict:
    return {
        "ticker": "HK.00700",
        "quarters": [
            {"period": "2024-09-30", "revenue": 167_200_000_000, "net_income": 33_200_000_000, "gross_profit": 80_300_000_000},
            {"period": "2024-06-30", "revenue": 161_100_000_000, "net_income": 30_900_000_000, "gross_profit": 77_800_000_000},
            {"period": "2024-03-31", "revenue": 159_500_000_000, "net_income": 27_600_000_000, "gross_profit": 76_100_000_000},
            {"period": "2023-12-31", "revenue": 155_200_000_000, "net_income": 27_300_000_000, "gross_profit": 74_000_000_000},
        ],
    }


def _mock_peers() -> dict:
    return {
        "ticker": "HK.00700",
        "peers": [
            {"ticker": "0700.HK",  "is_target": True,  "name": "Tencent Holdings",      "market_cap": 3_700_000_000_000, "current_price": 385.4,  "pe_ratio": 19.2,  "pb_ratio": 3.3,  "roe": 0.228, "eps_ttm": 20.08, "dividend_yield": 0.0055, "beta": 0.84, "ytd_return_pct": 12.4,  "recommendation": "buy"},
            {"ticker": "9988.HK",  "is_target": False, "name": "Alibaba Group",          "market_cap": 1_490_000_000_000, "current_price": 83.20,  "pe_ratio": 14.1,  "pb_ratio": 1.7,  "roe": 0.142, "eps_ttm":  5.90, "dividend_yield": 0.0000, "beta": 0.95, "ytd_return_pct":  3.8,  "recommendation": "buy"},
            {"ticker": "9618.HK",  "is_target": False, "name": "JD.com",                 "market_cap": 498_000_000_000,   "current_price": 130.60, "pe_ratio": 10.8,  "pb_ratio": 1.4,  "roe": 0.135, "eps_ttm": 12.10, "dividend_yield": 0.0230, "beta": 0.72, "ytd_return_pct":  8.9,  "recommendation": "hold"},
            {"ticker": "3690.HK",  "is_target": False, "name": "Meituan",                "market_cap": 720_000_000_000,   "current_price": 148.30, "pe_ratio": 22.3,  "pb_ratio": 4.1,  "roe": 0.182, "eps_ttm":  6.65, "dividend_yield": 0.0000, "beta": 1.05, "ytd_return_pct": -2.1,  "recommendation": "buy"},
            {"ticker": "9999.HK",  "is_target": False, "name": "NetEase",                "market_cap": 305_000_000_000,   "current_price": 120.80, "pe_ratio": 16.4,  "pb_ratio": 2.9,  "roe": 0.175, "eps_ttm":  7.36, "dividend_yield": 0.0420, "beta": 0.69, "ytd_return_pct":  5.2,  "recommendation": "hold"},
            {"ticker": "0268.HK",  "is_target": False, "name": "Kingsoft Corp",           "market_cap": 82_000_000_000,    "current_price": 18.46,  "pe_ratio": 25.1,  "pb_ratio": 2.2,  "roe": 0.089, "eps_ttm":  0.74, "dividend_yield": 0.0080, "beta": 0.91, "ytd_return_pct": -6.5,  "recommendation": "hold"},
        ],
        "sector_averages": {
            "pe_ratio": 18.0, "pb_ratio": 2.6, "roe": 0.159, "eps_ttm": 8.81,
            "dividend_yield": 0.012, "ytd_return_pct": 3.6,
        },
    }


def _mock_performance() -> dict:
    return {
        "ticker": "HK.00700",
        "yf_ticker": "0700.HK",
        "benchmark": "^HSI",
        "performance": [
            {"period": "1M",  "days":  30, "ticker_return_pct":  6.2, "benchmark_return_pct":  3.8, "alpha_pct":  2.4},
            {"period": "3M",  "days":  90, "ticker_return_pct": 14.1, "benchmark_return_pct":  9.3, "alpha_pct":  4.8},
            {"period": "6M",  "days": 180, "ticker_return_pct": 22.7, "benchmark_return_pct": 14.5, "alpha_pct":  8.2},
            {"period": "1Y",  "days": 365, "ticker_return_pct": -3.8, "benchmark_return_pct": -9.2, "alpha_pct":  5.4},
        ],
    }


def _mock_sentiment() -> dict:
    return {
        "score": 0.42,
        "label": "Positive",
        "articles": [
            {"title": "Tencent beats Q3 expectations with strong gaming and cloud growth",
             "source": "Reuters", "date": "2024-11-14", "sentiment": 0.75, "url": ""},
            {"title": "Tencent raises dividend as AI investments show early returns",
             "source": "Bloomberg", "date": "2024-11-12", "sentiment": 0.60, "url": ""},
            {"title": "China tech stocks rally on regulatory relief hopes",
             "source": "FT", "date": "2024-11-10", "sentiment": 0.50, "url": ""},
            {"title": "Analysts upgrade Tencent ahead of earnings report",
             "source": "Goldman Sachs Research", "date": "2024-11-08", "sentiment": 0.80, "url": ""},
            {"title": "WeChat monthly active users reach new record high",
             "source": "SCMP", "date": "2024-11-06", "sentiment": 0.65, "url": ""},
            {"title": "Tencent Music faces declining subscriber growth concerns",
             "source": "Caixin", "date": "2024-11-04", "sentiment": -0.30, "url": ""},
            {"title": "Regulatory investigation into fintech unit weighs on shares",
             "source": "WSJ", "date": "2024-11-02", "sentiment": -0.55, "url": ""},
            {"title": "Tencent Cloud revenue surges 30% year-on-year",
             "source": "TechCrunch", "date": "2024-10-31", "sentiment": 0.70, "url": ""},
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> str:
    print("Generating sample report for HK.00700 (Tencent)...")

    kline_records = _make_kline(180)
    df = pd.DataFrame(kline_records).rename(columns={"time_key": "date", "volume": "volume"})
    technicals = compute_all(df)

    last_price = kline_records[-1]["close"]
    snapshot   = _mock_snapshot(last_price)

    out_dir = ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)

    # Build synthetic peer/benchmark price series so the peer performance chart
    # renders without a live internet connection.
    from unittest.mock import patch as _patch

    def _mock_yf_download(tickers, start=None, end=None, **kwargs):
        """Return synthetic indexed price data for any requested ticker."""
        rng = np.random.default_rng(hash(str(tickers)) & 0xFFFFFFFF)
        n = 125  # ~6 months of trading days
        idx = pd.date_range(end=pd.Timestamp.today(), periods=n, freq="B")
        if isinstance(tickers, list):
            cols = pd.MultiIndex.from_product([["Close"], tickers])
            data = {("Close", t): 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.015, n)))
                    for t in tickers}
            return pd.DataFrame(data, index=idx, columns=cols)
        price = 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.015, n)))
        return pd.DataFrame({"Close": price}, index=idx)

    # Use a fixed "SAMPLE_" prefix so it doesn't collide with dated real reports
    from src.report_generator import generate_report as _gen
    import tempfile, shutil

    sample_path = out_dir / "SAMPLE_HK_00700_report.html"
    with _patch("src.report_generator.yf.download", side_effect=_mock_yf_download):
        with tempfile.TemporaryDirectory() as tmp:
            path = _gen(
                ticker="HK.00700",
                snapshot=snapshot,
                kline_records=kline_records,
                fundamentals=_mock_fundamentals(),
                earnings=_mock_earnings(),
                technicals=technicals,
                peers=_mock_peers(),
                performance=_mock_performance(),
                sentiment=_mock_sentiment(),
                output_dir=tmp,
            )
            shutil.copy(path, sample_path)

    size_kb = sample_path.stat().st_size / 1024
    print(f"[OK] Sample report saved: {sample_path}  ({size_kb:.0f} KB)")
    return str(sample_path)


if __name__ == "__main__":
    main()
