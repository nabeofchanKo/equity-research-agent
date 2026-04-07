"""
Tests for src/report_generator.py

Unit tests use synthetic data so no network or OpenD connection is needed.
An integration test (marked @pytest.mark.integration) writes a real HTML file
to the outputs/ directory.

Run unit tests only:
    pytest tests/test_report_generator.py -m "not integration"
"""

import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.report_generator import (
    _build_earnings_chart,
    _build_macd_chart,
    _build_performance_chart,
    _build_price_chart,
    _build_rsi_chart,
    _build_stoch_chart,
    _compare_class,
    _kline_to_df,
    _prepare_peers,
    fmt_large,
    fmt_num,
    fmt_pct,
    generate_report,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_kline(n: int = 60) -> list[dict]:
    import numpy as np
    rng = np.random.default_rng(42)
    prices = 300.0 + np.cumsum(rng.normal(0, 2, n))
    records = []
    for i, p in enumerate(prices):
        records.append({
            "time_key": f"2024-{(i // 30 + 1):02d}-{(i % 28 + 1):02d} 00:00:00",
            "open":   float(p * 0.998),
            "high":   float(p * 1.012),
            "low":    float(p * 0.988),
            "close":  float(p),
            "volume": int(abs(rng.normal(5_000_000, 1_000_000))),
        })
    return records


def _make_technicals() -> dict:
    return {
        "latest_price": 320.5,
        "sma":   {20: 318.0, 50: 310.0, 200: 290.0},
        "rsi":   {"value": 58.4, "period": 14},
        "macd":  {"macd": 1.23, "signal": 0.98, "histogram": 0.25, "fast": 12, "slow": 26, "signal_period": 9},
        "bollinger": {"upper": 335.0, "middle": 318.0, "lower": 301.0, "period": 20, "std": 2.0, "bandwidth": 0.106},
        "stochastic": {"k": 62.5, "d": 58.1},
        "support_resistance": {"support": [305.0, 295.0], "resistance": [330.0, 345.0]},
        "signal_score": 0.45,
        "signal_label": "Buy",
        "data_points": 60,
    }


def _make_snapshot() -> dict:
    return {
        "ticker": "HK.00700",
        "name": "Tencent Holdings Limited",
        "last_price": 320.5,
        "change_val": 4.2,
        "change_rate": 1.33,
        "volume": 12_000_000,
        "turnover": 3_900_000_000,
        "market_cap": 3_000_000_000_000,
        "pe_ratio": 18.5,
        "pb_ratio": 3.2,
        "52w_high": 430.0,
        "52w_low": 260.0,
        "dividend_yield": 0.0055,
    }


def _make_fundamentals() -> dict:
    return {
        "ticker": "HK.00700",
        "yf_ticker": "0700.HK",
        "name": "Tencent Holdings Limited",
        "sector": "Technology",
        "industry": "Internet Content & Information",
        "market_cap": 3_000_000_000_000,
        "currency": "HKD",
        "current_price": 320.5,
        "pe_ratio": 18.5,
        "pb_ratio": 3.2,
        "roe": 0.22,
        "eps_ttm": 17.3,
        "eps_forward": 21.0,
        "revenue_ttm": 609_000_000_000,
        "net_income_ttm": 115_000_000_000,
        "profit_margin": 0.189,
        "dividend_yield": 0.0055,
        "beta": 0.81,
        "52w_high": 430.0,
        "52w_low": 260.0,
        "book_value": 124.3,
        "debt_to_equity": 28.4,
        "current_ratio": 1.65,
        "analyst_target": 450.0,
        "recommendation": "buy",
    }


def _make_earnings() -> dict:
    return {
        "ticker": "HK.00700",
        "quarters": [
            {"period": "2024-09-30", "revenue": 161_000_000_000, "net_income": 32_000_000_000},
            {"period": "2024-06-30", "revenue": 149_000_000_000, "net_income": 28_000_000_000},
            {"period": "2024-03-31", "revenue": 150_000_000_000, "net_income": 27_000_000_000},
            {"period": "2023-12-31", "revenue": 155_000_000_000, "net_income": 29_000_000_000},
        ],
    }


def _make_peers() -> dict:
    return {
        "ticker": "HK.00700",
        "peers": [
            {
                "ticker": "0700.HK", "is_target": True, "name": "Tencent",
                "market_cap": 3_000_000_000_000, "current_price": 320.5,
                "pe_ratio": 18.5, "pb_ratio": 3.2, "roe": 0.22,
                "eps_ttm": 17.3, "dividend_yield": 0.0055, "ytd_return_pct": 8.4, "beta": 0.81,
            },
            {
                "ticker": "9988.HK", "is_target": False, "name": "Alibaba",
                "market_cap": 1_500_000_000_000, "current_price": 82.5,
                "pe_ratio": 14.2, "pb_ratio": 1.9, "roe": 0.14,
                "eps_ttm": 5.8, "dividend_yield": 0.0, "ytd_return_pct": -3.2, "beta": 0.95,
            },
        ],
        "sector_averages": {
            "pe_ratio": 16.0, "pb_ratio": 2.5, "roe": 0.18,
            "eps_ttm": 11.0, "dividend_yield": 0.003, "ytd_return_pct": 2.6,
        },
    }


def _make_performance() -> dict:
    return {
        "ticker": "HK.00700",
        "benchmark": "^HSI",
        "performance": [
            {"period": "1M",  "days": 30,  "ticker_return_pct":  3.2,  "benchmark_return_pct":  1.8,  "alpha_pct":  1.4},
            {"period": "3M",  "days": 90,  "ticker_return_pct":  8.5,  "benchmark_return_pct":  5.2,  "alpha_pct":  3.3},
            {"period": "6M",  "days": 180, "ticker_return_pct": 14.1,  "benchmark_return_pct":  9.7,  "alpha_pct":  4.4},
            {"period": "1Y",  "days": 365, "ticker_return_pct": -5.3,  "benchmark_return_pct": -8.1,  "alpha_pct":  2.8},
        ],
    }


def _make_sentiment() -> dict:
    return {
        "score": 0.35,
        "label": "Positive",
        "articles": [
            {"title": "Tencent beats Q3 estimates", "source": "Reuters",
             "date": "2024-11-14", "sentiment": 0.6},
            {"title": "Regulatory headwinds persist", "source": "Bloomberg",
             "date": "2024-11-12", "sentiment": -0.3},
        ],
    }


def _all_args(kline_override=None, output_dir=None) -> dict:
    return dict(
        ticker="HK.00700",
        snapshot=_make_snapshot(),
        kline_records=kline_override or _make_kline(),
        fundamentals=_make_fundamentals(),
        earnings=_make_earnings(),
        technicals=_make_technicals(),
        peers=_make_peers(),
        performance=_make_performance(),
        sentiment=_make_sentiment(),
        output_dir=output_dir or tempfile.mkdtemp(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestFmtNum:
    def test_basic(self):           assert fmt_num(1234.567, 2) == "1,234.57"
    def test_none_returns_dash(self): assert fmt_num(None) == "—"
    def test_prefix_suffix(self):   assert fmt_num(5.0, 1, suffix="%") == "5.0%"
    def test_zero(self):            assert fmt_num(0.0) == "0.00"
    def test_string_convertible(self): assert fmt_num("12.5", 1) == "12.5"
    def test_invalid_string(self):  assert fmt_num("N/A") == "N/A"


class TestFmtLarge:
    def test_trillions(self):  assert "T"  in fmt_large(3e12)
    def test_billions(self):   assert "B"  in fmt_large(3e9)
    def test_millions(self):   assert "M"  in fmt_large(3e6)
    def test_small(self):      assert "," in fmt_large(1234)  # formatted with commas
    def test_none(self):       assert fmt_large(None) == "—"


class TestFmtPct:
    def test_decimal_form(self):    assert fmt_pct(0.22) == "22.00%"
    def test_pct_form(self):        assert fmt_pct(22.5) == "22.50%"
    def test_none(self):            assert fmt_pct(None) == "—"
    def test_zero(self):            assert fmt_pct(0.0) == "0.00%"


class TestCompareClass:
    def test_above_higher_is_better(self): assert _compare_class(10, 5)   == "cell-above"
    def test_below_higher_is_better(self): assert _compare_class(5, 10)   == "cell-below"
    def test_lower_is_better_reversed(self): assert _compare_class(10, 5, True) == "cell-below"
    def test_none_val_returns_empty(self):   assert _compare_class(None, 5) == ""
    def test_none_avg_returns_empty(self):   assert _compare_class(5, None) == ""


# ─────────────────────────────────────────────────────────────────────────────
# _kline_to_df
# ─────────────────────────────────────────────────────────────────────────────

class TestKlineToDf:
    def test_basic_conversion(self):
        records = _make_kline(10)
        df = _kline_to_df(records)
        assert len(df) == 10
        assert "date" in df.columns

    def test_sorted_chronologically(self):
        records = _make_kline(20)
        records.reverse()          # scramble order
        df = _kline_to_df(records)
        assert (df["date"].diff().dropna() >= pd.Timedelta(0)).all()

    def test_empty_returns_empty(self):
        import pandas as pd
        df = _kline_to_df([])
        assert df.empty

    def test_trade_vol_alias(self):
        records = [{"time_key": "2024-01-01", "open": 1, "high": 1, "low": 1,
                    "close": 1, "trade_vol": 999}]
        df = _kline_to_df(records)
        assert "volume" in df.columns


# ─────────────────────────────────────────────────────────────────────────────
# Chart builders return valid Plotly JSON
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd


def _df():
    return _kline_to_df(_make_kline(60))


class TestBuildPriceChart:
    def test_returns_valid_json(self):
        fig = json.loads(_build_price_chart(_df(), _make_technicals()))
        assert "data" in fig
        assert "layout" in fig

    def test_has_candlestick_trace(self):
        fig = json.loads(_build_price_chart(_df(), _make_technicals()))
        types = [t.get("type") for t in fig["data"]]
        assert "candlestick" in types

    def test_has_volume_bar_trace(self):
        fig = json.loads(_build_price_chart(_df(), _make_technicals()))
        types = [t.get("type") for t in fig["data"]]
        assert "bar" in types

    def test_has_sma_traces(self):
        fig = json.loads(_build_price_chart(_df(), _make_technicals()))
        names = [t.get("name", "") for t in fig["data"]]
        assert any("SMA" in n for n in names)

    def test_empty_df_returns_empty_figure(self):
        fig = json.loads(_build_price_chart(pd.DataFrame(), {}))
        assert "data" in fig


class TestBuildRsiChart:
    def test_returns_valid_json(self):
        fig = json.loads(_build_rsi_chart(_df()))
        assert "data" in fig

    def test_y_range_0_to_100(self):
        fig = json.loads(_build_rsi_chart(_df()))
        assert fig["layout"]["yaxis"]["range"] == [0, 100]


class TestBuildMacdChart:
    def test_returns_valid_json(self):
        fig = json.loads(_build_macd_chart(_df()))
        assert len(fig["data"]) == 3  # bar + 2 lines

    def test_trace_names(self):
        fig = json.loads(_build_macd_chart(_df()))
        names = [t.get("name", "") for t in fig["data"]]
        assert any("MACD" in n for n in names)
        assert any("Signal" in n for n in names)


class TestBuildStochChart:
    def test_returns_valid_json(self):
        fig = json.loads(_build_stoch_chart(_df()))
        assert len(fig["data"]) == 2  # %K and %D

    def test_y_range_0_to_100(self):
        fig = json.loads(_build_stoch_chart(_df()))
        assert fig["layout"]["yaxis"]["range"] == [0, 100]


class TestBuildEarningsChart:
    def test_returns_valid_json(self):
        fig = json.loads(_build_earnings_chart(_make_earnings()["quarters"]))
        assert len(fig["data"]) == 2  # revenue + net income

    def test_empty_returns_empty_figure(self):
        fig = json.loads(_build_earnings_chart([]))
        assert "data" in fig

    def test_group_barmode(self):
        fig = json.loads(_build_earnings_chart(_make_earnings()["quarters"]))
        assert fig["layout"]["barmode"] == "group"


class TestBuildPerformanceChart:
    def test_returns_valid_json(self):
        fig = json.loads(_build_performance_chart(_make_performance()["performance"]))
        assert len(fig["data"]) == 2  # stock + benchmark

    def test_empty_returns_empty_figure(self):
        fig = json.loads(_build_performance_chart([]))
        assert "data" in fig


# ─────────────────────────────────────────────────────────────────────────────
# _prepare_peers
# ─────────────────────────────────────────────────────────────────────────────

class TestPreparePeers:
    def test_adds_format_fields(self):
        rows = _prepare_peers(_make_peers())
        assert all("pe_fmt" in r for r in rows)
        assert all("roe_fmt" in r for r in rows)
        assert all("mktcap_fmt" in r for r in rows)

    def test_compare_classes_set(self):
        rows = _prepare_peers(_make_peers())
        assert all("pe_class" in r for r in rows)

    def test_target_row_preserved(self):
        rows = _prepare_peers(_make_peers())
        targets = [r for r in rows if r["is_target"]]
        assert len(targets) == 1


# ─────────────────────────────────────────────────────────────────────────────
# generate_report — file creation
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateReport:
    def test_creates_html_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            assert Path(path).exists()
            assert path.endswith(".html")

    def test_filename_contains_ticker_and_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            filename = Path(path).name
            assert "00700" in filename
            assert date.today().isoformat() in filename

    def test_returns_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            assert Path(path).is_absolute()

    def test_output_dir_created_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            new_dir = Path(tmp) / "subdir" / "reports"
            generate_report(**_all_args(output_dir=str(new_dir)))
            assert new_dir.exists()

    def test_file_is_non_empty_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            content = Path(path).read_text(encoding="utf-8")
            assert len(content) > 10_000   # meaningful HTML
            assert "<!DOCTYPE html>" in content

    def test_valid_html_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
            assert "<html" in html
            assert "</html>" in html
            assert "<body" in html
            assert "</body>" in html

    def test_all_seven_sections_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        section_markers = [
            "section-price",
            "section-technicals",
            "section-fundamentals",
            "section-peers",
            "section-performance",
            "section-sentiment",
            "chart-price",
            "chart-rsi",
            "chart-macd",
            "chart-stoch",
            "chart-earnings",
            "chart-performance",
            "chart-sentiment",
            "chart-signal",
        ]
        for marker in section_markers:
            assert marker in html, f"Missing section/chart: {marker}"

    def test_contains_plotly_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        assert "plotly" in html.lower()
        assert "Plotly.react" in html

    def test_contains_company_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        assert "Tencent" in html

    def test_contains_ticker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        assert "00700" in html

    def test_contains_chart_data(self):
        """Plotly chart JSON should be embedded inline in the HTML."""
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        # Each call to Plotly.react should have JSON with "data" key
        assert '"data"' in html
        assert '"layout"' in html

    def test_navigation_links_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        for anchor in ["#section-price", "#section-technicals",
                        "#section-fundamentals", "#section-peers",
                        "#section-performance", "#section-sentiment"]:
            assert anchor in html

    def test_sentiment_none_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _all_args(output_dir=tmp)
            args["sentiment"] = None
            path = generate_report(**args)
            html = Path(path).read_text(encoding="utf-8")
        assert "chart-sentiment" in html

    def test_empty_kline_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(kline_override=[], output_dir=tmp))
            assert Path(path).exists()

    def test_signal_label_in_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        assert "Buy" in html

    def test_support_resistance_levels_in_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        assert "305.000" in html or "305" in html   # support level from fixture

    def test_news_headlines_in_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        assert "Tencent beats Q3" in html

    def test_peer_table_has_both_tickers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        assert "0700.HK" in html
        assert "9988.HK" in html

    def test_performance_periods_in_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        for period in ["1M", "3M", "6M", "1Y"]:
            assert period in html

    def test_self_contained_no_external_css(self):
        """No <link> tags for external CSS (fonts/CDN scripts are OK via <script src>)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        # Should not reference any local .css files
        local_css = re.findall(r'<link[^>]+href=["\'](?!https?)([^"\']+\.css)', html)
        assert local_css == [], f"Found local CSS references: {local_css}"

    def test_google_fonts_referenced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_report(**_all_args(output_dir=tmp))
            html = Path(path).read_text(encoding="utf-8")
        assert "fonts.googleapis.com" in html


# ─────────────────────────────────────────────────────────────────────────────
# Integration test — writes a real HTML file to outputs/
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestReportIntegration:
    def test_full_report_written_to_outputs(self):
        """Generates the report into the real outputs/ directory."""
        project_root = Path(__file__).parent.parent
        out_dir = project_root / "outputs"
        path = generate_report(
            ticker="HK.00700",
            snapshot=_make_snapshot(),
            kline_records=_make_kline(120),
            fundamentals=_make_fundamentals(),
            earnings=_make_earnings(),
            technicals=_make_technicals(),
            peers=_make_peers(),
            performance=_make_performance(),
            sentiment=_make_sentiment(),
            output_dir=str(out_dir),
        )
        assert Path(path).exists()
        size_kb = Path(path).stat().st_size / 1024
        # A chart-heavy self-contained report should be well over 100 KB
        assert size_kb > 100, f"Report suspiciously small: {size_kb:.1f} KB"
        print(f"\n✓ Integration report: {path} ({size_kb:.0f} KB)")
