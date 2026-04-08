"""
Tests for mcp_servers/financials_server/server.py

All tests mock yfinance so no network call is made.
Integration tests (marked @pytest.mark.integration) hit the real yfinance API.

Run unit tests only:
    pytest tests/test_financials_server.py -m "not integration"
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Import the server module by file path under a unique module name.
# ---------------------------------------------------------------------------
import importlib.util as _ilu

_SERVER_FILE = Path(__file__).parent.parent / "mcp_servers" / "financials_server" / "server.py"
_SERVER_DIR  = str(_SERVER_FILE.parent)
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

_spec = _ilu.spec_from_file_location("financials_server_mod", _SERVER_FILE)
fin_server = _ilu.module_from_spec(_spec)
sys.modules["financials_server_mod"] = fin_server
_spec.loader.exec_module(fin_server)

get_fundamentals  = fin_server.get_fundamentals
get_earnings      = fin_server.get_earnings
get_peer_comparison = fin_server.get_peer_comparison
get_performance   = fin_server.get_performance
_to_yf            = fin_server._to_yf


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_TENCENT_INFO = {
    "longName": "Tencent Holdings Limited",
    "shortName": "TENCENT",
    "sector": "Technology",
    "industry": "Internet Content & Information",
    "marketCap": 3_700_000_000_000,
    "currency": "HKD",
    "currentPrice": 385.2,
    "trailingPE": 18.5,
    "forwardPE": 15.2,
    "priceToBook": 3.1,
    "priceToSalesTrailing12Months": 4.2,
    "returnOnEquity": 0.22,
    "returnOnAssets": 0.11,
    "trailingEps": 20.8,
    "forwardEps": 25.3,
    "totalRevenue": 609_000_000_000,
    "netIncomeToCommon": 115_000_000_000,
    "profitMargins": 0.189,
    "dividendYield": 0.0055,
    "dividendRate": 2.12,
    "beta": 0.81,
    "fiftyTwoWeekHigh": 430.0,
    "fiftyTwoWeekLow": 260.0,
    "sharesOutstanding": 9_600_000_000,
    "bookValue": 124.3,
    "debtToEquity": 28.4,
    "currentRatio": 1.65,
    "grossMargins": 0.48,
    "operatingMargins": 0.22,
    "ebitda": 180_000_000_000,
    "enterpriseValue": 3_600_000_000_000,
    "enterpriseToEbitda": 20.0,
    "enterpriseToRevenue": 5.9,
    "targetMeanPrice": 450.0,
    "recommendationKey": "buy",
}

_AAPL_INFO = {
    "longName": "Apple Inc.",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "marketCap": 3_000_000_000_000,
    "currency": "USD",
    "currentPrice": 195.0,
    "trailingPE": 30.2,
    "priceToBook": 48.5,
    "returnOnEquity": 1.47,
    "trailingEps": 6.46,
    "dividendYield": 0.0054,
    "beta": 1.25,
    "fiftyTwoWeekHigh": 220.0,
    "fiftyTwoWeekLow": 165.0,
    "recommendationKey": "buy",
}


def _make_yf_ticker(info: dict, quarterly_financials=None, quarterly_earnings=None):
    t = MagicMock()
    t.info = info
    t.quarterly_financials = quarterly_financials if quarterly_financials is not None else pd.DataFrame()
    t.quarterly_earnings = quarterly_earnings if quarterly_earnings is not None else pd.DataFrame()
    return t


def _make_history(prices: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="B")
    return pd.DataFrame({"Close": prices}, index=idx)


# ---------------------------------------------------------------------------
# _to_yf helper
# ---------------------------------------------------------------------------

class TestToYf:
    def test_hk_moomoo_format(self):
        assert _to_yf("HK.00700") == "0700.HK"

    def test_us_moomoo_format(self):
        assert _to_yf("US.AAPL") == "AAPL"

    def test_already_yf_hk(self):
        assert _to_yf("0700.HK") == "0700.HK"

    def test_already_yf_us(self):
        assert _to_yf("AAPL") == "AAPL"

    def test_whitespace_stripped(self):
        assert _to_yf("  US.AAPL  ") == "AAPL"


# ---------------------------------------------------------------------------
# get_fundamentals
# ---------------------------------------------------------------------------

class TestGetFundamentals:
    def _call(self, ticker: str, info: dict):
        with patch.object(fin_server.yf, "Ticker", return_value=_make_yf_ticker(info)):
            return json.loads(get_fundamentals(ticker))

    def test_returns_expected_fields(self):
        result = self._call("HK.00700", _TENCENT_INFO)
        assert result["name"] == "Tencent Holdings Limited"
        assert result["sector"] == "Technology"
        assert result["pe_ratio"] == pytest.approx(18.5)
        assert result["pb_ratio"] == pytest.approx(3.1)
        assert result["dividend_yield"] == pytest.approx(0.0055)
        assert result["beta"] == pytest.approx(0.81)
        assert result["52w_high"] == pytest.approx(430.0)
        assert result["52w_low"] == pytest.approx(260.0)

    def test_ticker_field_preserved(self):
        result = self._call("HK.00700", _TENCENT_INFO)
        assert result["ticker"] == "HK.00700"
        assert result["yf_ticker"] == "0700.HK"

    def test_empty_info_returns_error(self):
        with patch.object(fin_server.yf, "Ticker", return_value=_make_yf_ticker({})):
            result = json.loads(get_fundamentals("HK.00700"))
        assert "error" in result

    def test_yfinance_exception_returns_error(self):
        with patch.object(fin_server.yf, "Ticker", side_effect=Exception("timeout")):
            result = json.loads(get_fundamentals("HK.00700"))
        assert "error" in result

    def test_nan_values_serialised_as_none(self):
        import math
        info = {**_AAPL_INFO, "trailingPE": float("nan")}
        result = self._call("AAPL", info)
        assert result["pe_ratio"] is None

    def test_roe_returned_as_decimal(self):
        result = self._call("HK.00700", _TENCENT_INFO)
        # ROE stored as decimal (0.22 not 22)
        assert result["roe"] == pytest.approx(0.22, abs=0.0001)

    def test_us_ticker_works(self):
        result = self._call("US.AAPL", _AAPL_INFO)
        assert result["yf_ticker"] == "AAPL"
        assert result["name"] == "Apple Inc."


# ---------------------------------------------------------------------------
# get_earnings
# ---------------------------------------------------------------------------

class TestGetEarnings:
    def _make_financials(self) -> pd.DataFrame:
        periods = pd.to_datetime(["2024-09-30", "2024-06-30", "2024-03-31", "2023-12-31"])
        data = {
            periods[0]: {"Total Revenue": 600e9, "Net Income": 120e9, "Gross Profit": 280e9, "EBITDA": 180e9},
            periods[1]: {"Total Revenue": 580e9, "Net Income": 110e9, "Gross Profit": 270e9, "EBITDA": 170e9},
            periods[2]: {"Total Revenue": 560e9, "Net Income": 100e9, "Gross Profit": 260e9, "EBITDA": 160e9},
            periods[3]: {"Total Revenue": 540e9, "Net Income":  90e9, "Gross Profit": 250e9, "EBITDA": 150e9},
        }
        return pd.DataFrame(data)

    def test_returns_four_quarters(self):
        fin_df = self._make_financials()
        t = _make_yf_ticker(_TENCENT_INFO, quarterly_financials=fin_df)
        with patch.object(fin_server.yf, "Ticker", return_value=t):
            result = json.loads(get_earnings("HK.00700"))
        assert "quarters" in result
        assert len(result["quarters"]) == 4

    def test_quarter_has_required_fields(self):
        fin_df = self._make_financials()
        t = _make_yf_ticker(_TENCENT_INFO, quarterly_financials=fin_df)
        with patch.object(fin_server.yf, "Ticker", return_value=t):
            result = json.loads(get_earnings("HK.00700"))
        q = result["quarters"][0]
        assert "period" in q
        assert "revenue" in q
        assert "net_income" in q

    def test_empty_financials_returns_error(self):
        t = _make_yf_ticker(_TENCENT_INFO, quarterly_financials=pd.DataFrame())
        with patch.object(fin_server.yf, "Ticker", return_value=t):
            result = json.loads(get_earnings("HK.00700"))
        assert "error" in result

    def test_yfinance_exception_returns_error(self):
        with patch.object(fin_server.yf, "Ticker", side_effect=RuntimeError("no data")):
            result = json.loads(get_earnings("HK.00700"))
        assert "error" in result


# ---------------------------------------------------------------------------
# get_peer_comparison
# ---------------------------------------------------------------------------

class TestGetPeerComparison:
    def _make_peer_ticker(self, name: str) -> MagicMock:
        info = {
            "longName": name,
            "sector": "Technology",
            "marketCap": 500_000_000_000,
            "currentPrice": 100.0,
            "trailingPE": 20.0,
            "priceToBook": 3.0,
            "returnOnEquity": 0.15,
            "trailingEps": 5.0,
            "dividendYield": 0.01,
            "beta": 1.0,
            "recommendationKey": "hold",
        }
        t = MagicMock()
        t.info = info
        t.history.return_value = _make_history([90.0, 100.0])
        return t

    def test_target_row_marked_is_target(self):
        target_ticker = _make_yf_ticker(
            _TENCENT_INFO,
        )
        target_ticker.history = MagicMock(return_value=_make_history([350.0, 385.2]))
        peer1 = self._make_peer_ticker("Peer A")
        peer2 = self._make_peer_ticker("Peer B")

        side_effects = [target_ticker, peer1, peer2]

        with patch("src.sector_mapper.yf.Ticker", return_value=_make_yf_ticker({"sector": "Technology"})), \
             patch.object(fin_server.yf, "Ticker", side_effect=side_effects):
            result = json.loads(get_peer_comparison("HK.00700", max_peers=2))

        assert "peers" in result
        target_rows = [r for r in result["peers"] if r.get("is_target")]
        assert len(target_rows) == 1

    def test_sector_averages_computed(self):
        target_ticker = _make_yf_ticker(_TENCENT_INFO)
        target_ticker.history = MagicMock(return_value=_make_history([350.0, 385.2]))

        with patch("src.sector_mapper.yf.Ticker", return_value=_make_yf_ticker({"sector": "Technology"})), \
             patch.object(fin_server.yf, "Ticker", return_value=target_ticker):
            result = json.loads(get_peer_comparison("HK.00700", max_peers=0))

        assert "sector_averages" in result

    def test_yfinance_exception_returns_error(self):
        with patch("src.sector_mapper.yf.Ticker", side_effect=Exception("err")), \
             patch.object(fin_server.yf, "Ticker", side_effect=Exception("err")):
            result = json.loads(get_peer_comparison("HK.00700"))
        assert "error" in result


# ---------------------------------------------------------------------------
# get_performance
# ---------------------------------------------------------------------------

class TestGetPerformance:
    def _make_download_df(self, ticker: str, bench: str) -> pd.DataFrame:
        idx = pd.date_range("2023-04-01", periods=260, freq="B")
        cols = pd.MultiIndex.from_tuples(
            [("Close", ticker), ("Close", bench)],
            names=["Price", "Ticker"],
        )
        data = {
            ("Close", ticker): [100.0 + i * 0.5 for i in range(260)],
            ("Close", bench):  [100.0 + i * 0.3 for i in range(260)],
        }
        return pd.DataFrame(data, index=idx, columns=cols)

    def test_returns_four_periods(self):
        df = self._make_download_df("0700.HK", "^HSI")
        with patch.object(fin_server.yf, "download", return_value=df):
            result = json.loads(get_performance("HK.00700"))
        assert "performance" in result
        assert len(result["performance"]) == 4
        labels = [r["period"] for r in result["performance"]]
        assert labels == ["1M", "3M", "6M", "1Y"]

    def test_alpha_computed(self):
        df = self._make_download_df("0700.HK", "^HSI")
        with patch.object(fin_server.yf, "download", return_value=df):
            result = json.loads(get_performance("HK.00700"))
        for r in result["performance"]:
            if r["ticker_return_pct"] is not None and r["benchmark_return_pct"] is not None:
                assert r["alpha_pct"] == pytest.approx(
                    r["ticker_return_pct"] - r["benchmark_return_pct"], abs=0.01
                )

    def test_default_benchmark_hk(self):
        df = self._make_download_df("0700.HK", "^HSI")
        with patch.object(fin_server.yf, "download", return_value=df) as mock_dl:
            get_performance("HK.00700")
        call_args = mock_dl.call_args
        assert "^HSI" in call_args[0][0]

    def test_default_benchmark_us(self):
        df = self._make_download_df("AAPL", "SPY")
        with patch.object(fin_server.yf, "download", return_value=df) as mock_dl:
            get_performance("US.AAPL")
        call_args = mock_dl.call_args
        assert "SPY" in call_args[0][0]

    def test_explicit_benchmark_used(self):
        df = self._make_download_df("AAPL", "^IXIC")
        with patch.object(fin_server.yf, "download", return_value=df) as mock_dl:
            get_performance("US.AAPL", benchmark="^IXIC")
        call_args = mock_dl.call_args
        assert "^IXIC" in call_args[0][0]

    def test_download_exception_returns_error(self):
        with patch.object(fin_server.yf, "download", side_effect=Exception("timeout")):
            result = json.loads(get_performance("HK.00700"))
        assert "error" in result

    def test_ticker_and_benchmark_in_result(self):
        df = self._make_download_df("0700.HK", "^HSI")
        with patch.object(fin_server.yf, "download", return_value=df):
            result = json.loads(get_performance("HK.00700"))
        assert result["yf_ticker"] == "0700.HK"
        assert result["benchmark"] == "^HSI"


# ---------------------------------------------------------------------------
# Integration tests — require internet access
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFinancialsIntegration:
    """Live yfinance calls. Run with: pytest -m integration"""

    TICKER_HK = "HK.00700"
    TICKER_US = "US.AAPL"

    def test_fundamentals_hk_real(self):
        result = json.loads(get_fundamentals(self.TICKER_HK))
        assert "error" not in result, result.get("error")
        assert result["yf_ticker"] == "0700.HK"
        assert isinstance(result.get("current_price"), (int, float))

    def test_fundamentals_us_real(self):
        result = json.loads(get_fundamentals(self.TICKER_US))
        assert "error" not in result, result.get("error")
        assert result["yf_ticker"] == "AAPL"

    def test_earnings_us_real(self):
        result = json.loads(get_earnings(self.TICKER_US))
        assert "error" not in result, result.get("error")
        assert len(result["quarters"]) >= 1

    def test_performance_hk_real(self):
        result = json.loads(get_performance(self.TICKER_HK))
        assert "error" not in result, result.get("error")
        assert len(result["performance"]) == 4
        # At least the 1M period should have data
        assert result["performance"][0]["ticker_return_pct"] is not None

    def test_performance_us_real(self):
        result = json.loads(get_performance(self.TICKER_US))
        assert "error" not in result, result.get("error")
        assert result["benchmark"] == "^GSPC"
