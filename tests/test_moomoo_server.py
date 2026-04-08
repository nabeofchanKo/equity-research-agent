"""
Tests for mcp_servers/moomoo_server/server.py

Unit tests mock the moomoo SDK so OpenD does not need to be running.
Integration tests (marked @pytest.mark.integration) hit the real OpenD at
127.0.0.1:11111 and require HK LV1 market access to pass.

Run unit tests only:
    pytest tests/test_moomoo_server.py -m "not integration"

Run everything (OpenD must be running):
    pytest tests/test_moomoo_server.py
"""

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Import the server module by file path under a unique module name so that
# multiple server.py files can coexist in sys.modules during a combined run.
# ---------------------------------------------------------------------------
import importlib.util as _ilu

_SERVER_FILE = Path(__file__).parent.parent / "mcp_servers" / "moomoo_server" / "server.py"
_SERVER_DIR  = str(_SERVER_FILE.parent)
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)   # needed for relative imports inside server.py

_spec = _ilu.spec_from_file_location("moomoo_server_mod", _SERVER_FILE)
moomoo_server = _ilu.module_from_spec(_spec)
sys.modules["moomoo_server_mod"] = moomoo_server
_spec.loader.exec_module(moomoo_server)

# Convenience re-imports of the tool functions
_normalize_ticker = moomoo_server._normalize_ticker
get_snapshot = moomoo_server.get_snapshot
get_kline = moomoo_server.get_kline
get_plate_list = moomoo_server.get_plate_list
get_plate_stocks = moomoo_server.get_plate_stocks
get_plate_for_stock = moomoo_server.get_plate_for_stock
get_multi_snapshot = moomoo_server.get_multi_snapshot


# ---------------------------------------------------------------------------
# Shared DataFrame fixtures
# ---------------------------------------------------------------------------

def _snapshot_df(code: str = "HK.00700") -> pd.DataFrame:
    return pd.DataFrame([{
        "code": code,
        "name": "Tencent",
        "last_price": 385.2,
        "change_val": 3.4,
        "change_rate": 0.89,
        "volume": 12_000_000,
        "turnover": 4_620_000_000,
        "market_cap": 3_700_000_000_000,
        "pe_ratio": 18.5,
        "pb_ratio": 3.1,
        "high_price_52weeks": 430.0,
        "low_price_52weeks": 260.0,
        "dividend_yield": 0.55,
        "lot_size": 100,
        "stock_type": "STOCK",
        "listing_date": "2004-06-16",
    }])


def _kline_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "time_key": "2024-01-02 00:00:00",
            "open": 370.0, "close": 375.0, "high": 378.0, "low": 368.0,
            "volume": 8_000_000, "turnover": 3_000_000_000,
            "change_rate": 1.35, "last_close": 370.0,
            "pe_ratio": 18.1, "pb_ratio": 3.0,
        },
        {
            "time_key": "2024-01-03 00:00:00",
            "open": 375.0, "close": 380.0, "high": 382.0, "low": 373.0,
            "volume": 9_200_000, "turnover": 3_500_000_000,
            "change_rate": 1.33, "last_close": 375.0,
            "pe_ratio": 18.3, "pb_ratio": 3.05,
        },
    ])


def _plate_list_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"plate_id": "HK.BK1001", "plate_name": "Technology", "plate_type": "INDUSTRY"},
        {"plate_id": "HK.BK1002", "plate_name": "Finance",    "plate_type": "INDUSTRY"},
    ])


def _plate_stocks_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"code": "HK.00700", "name": "Tencent",    "lot_size": 100, "stock_type": "STOCK"},
        {"code": "HK.09988", "name": "Alibaba",    "lot_size": 100, "stock_type": "STOCK"},
        {"code": "HK.03690", "name": "Meituan",    "lot_size": 200, "stock_type": "STOCK"},
    ])


def _owner_plate_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"plate_code": "HK.BK1001", "plate_name": "Technology", "plate_type": "INDUSTRY"},
    ])


# ---------------------------------------------------------------------------
# Helper: build a mock OpenQuoteContext
# ---------------------------------------------------------------------------

def _make_ctx_mock(
    snapshot_ret=(0, _snapshot_df()),
    kline_ret=(0, _kline_df(), None),
    plate_list_ret=(0, _plate_list_df()),
    plate_stocks_ret=(0, _plate_stocks_df()),
    stock_basicinfo_ret=(0, pd.DataFrame()),
    owner_plate_ret=(0, _owner_plate_df()),
):
    ctx = MagicMock()
    ctx.get_market_snapshot.return_value = snapshot_ret
    ctx.get_history_kline.return_value = kline_ret
    ctx.get_plate_list.return_value = plate_list_ret
    ctx.get_plate_stock.return_value = plate_stocks_ret
    ctx.get_stock_basicinfo.return_value = stock_basicinfo_ret
    ctx.get_owner_plate.return_value = owner_plate_ret
    ctx.close.return_value = None
    return ctx


# ---------------------------------------------------------------------------
# _normalize_ticker
# ---------------------------------------------------------------------------

class TestNormalizeTicker:
    def test_adds_hk_prefix_by_default(self):
        assert _normalize_ticker("00700") == "HK.00700"

    def test_preserves_existing_hk_prefix(self):
        assert _normalize_ticker("HK.00700") == "HK.00700"

    def test_preserves_existing_us_prefix(self):
        assert _normalize_ticker("US.AAPL") == "US.AAPL"

    def test_lowercases_then_uppercases(self):
        assert _normalize_ticker("hk.00700") == "HK.00700"

    def test_explicit_default_market(self):
        assert _normalize_ticker("AAPL", default_market="US") == "US.AAPL"

    def test_strips_whitespace(self):
        assert _normalize_ticker("  HK.00700  ") == "HK.00700"


# ---------------------------------------------------------------------------
# get_snapshot — unit tests
# ---------------------------------------------------------------------------

def _mock_yf_info(ticker):
    """Minimal yfinance Ticker stub for fallback tests."""
    mock = MagicMock()
    mock.info = {
        "longName": "Tencent Holdings",
        "currentPrice": 385.0,
        "regularMarketPreviousClose": 381.6,
        "regularMarketVolume": 12_000_000,
        "marketCap": 3_700_000_000_000,
        "trailingPE": 18.5,
        "priceToBook": 3.1,
        "fiftyTwoWeekHigh": 430.0,
        "fiftyTwoWeekLow": 260.0,
        "dividendYield": 0.0055,
    }
    return mock


class TestGetSnapshot:
    def test_success_returns_expected_fields(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_snapshot("HK.00700"))

        assert result["ticker"] == "HK.00700"
        assert result["name"] == "Tencent"
        assert result["last_price"] == 385.2
        assert result["pe_ratio"] == 18.5
        assert result["pb_ratio"] == 3.1
        assert result["52w_high"] == 430.0
        assert result["52w_low"] == 260.0
        assert result["dividend_yield"] == 0.55

    def test_success_includes_source_moomoo(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_snapshot("HK.00700"))
        assert result.get("source") == "moomoo"

    def test_auto_prefix_applied(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            get_snapshot("00700")
        ctx_mock.get_market_snapshot.assert_called_once_with(["HK.00700"])

    def test_permission_error_falls_back_to_yfinance(self):
        import moomoo as ft
        import yfinance as yf
        ctx_mock = _make_ctx_mock(snapshot_ret=(ft.RET_ERROR, "No right to get the quote"))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            with patch.object(yf, "Ticker", return_value=_mock_yf_info("HK.00700")):
                result = json.loads(get_snapshot("HK.00700"))
        assert result.get("source") == "yfinance"
        assert result["last_price"] == 385.0

    def test_connection_error_falls_back_to_yfinance(self):
        import yfinance as yf
        with patch.object(moomoo_server, "_quote_ctx", side_effect=ConnectionError("refused")):
            with patch.object(yf, "Ticker", return_value=_mock_yf_info("HK.00700")):
                result = json.loads(get_snapshot("HK.00700"))
        assert result.get("source") == "yfinance"

    def test_non_permission_api_error_returns_error_json(self):
        """Non-permission API errors (e.g. symbol not found) should NOT fall back."""
        import moomoo as ft
        ctx_mock = _make_ctx_mock(snapshot_ret=(ft.RET_ERROR, "symbol not found"))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_snapshot("HK.00700"))
        assert "error" in result

    def test_empty_dataframe_returns_error_json(self):
        ctx_mock = _make_ctx_mock(snapshot_ret=(0, pd.DataFrame()))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_snapshot("HK.00700"))
        assert "error" in result

    def test_ctx_is_closed_on_success(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            get_snapshot("HK.00700")
        ctx_mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# get_kline — unit tests
# ---------------------------------------------------------------------------

def _mock_yf_download(*args, **kwargs):
    """Minimal yf.download stub returning 2 rows."""
    import numpy as np
    idx = pd.date_range("2024-01-02", periods=2, freq="B")
    return pd.DataFrame({
        "Open": [370.0, 375.0], "High": [378.0, 382.0],
        "Low": [368.0, 373.0], "Close": [375.0, 380.0],
        "Volume": [8_000_000, 9_200_000],
    }, index=idx)


class TestGetKline:
    def test_success_returns_records(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_kline("HK.00700", days=5, kline_type="K_DAY"))

        assert result["ticker"] == "HK.00700"
        assert result["kline_type"] == "K_DAY"
        assert len(result["records"]) == 2
        assert result["records"][0]["close"] == 375.0

    def test_success_includes_source_moomoo(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_kline("HK.00700"))
        assert result.get("source") == "moomoo"

    def test_default_kline_type_is_k_day(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            get_kline("HK.00700")
        import moomoo as ft
        _, call_kwargs = ctx_mock.get_history_kline.call_args
        assert call_kwargs.get("ktype") == ft.KLType.K_DAY

    def test_invalid_kline_type_falls_back_to_k_day(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            get_kline("HK.00700", kline_type="K_INVALID")
        import moomoo as ft
        _, call_kwargs = ctx_mock.get_history_kline.call_args
        assert call_kwargs.get("ktype") == ft.KLType.K_DAY

    def test_permission_error_falls_back_to_yfinance(self):
        import moomoo as ft
        import yfinance as yf
        ctx_mock = _make_ctx_mock(kline_ret=(ft.RET_ERROR, "No right to get the quote", None))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            with patch.object(yf, "download", side_effect=_mock_yf_download):
                result = json.loads(get_kline("HK.00700"))
        assert result.get("source") == "yfinance"
        assert len(result["records"]) == 2

    def test_connection_error_falls_back_to_yfinance(self):
        import yfinance as yf
        with patch.object(moomoo_server, "_quote_ctx", side_effect=OSError("timeout")):
            with patch.object(yf, "download", side_effect=_mock_yf_download):
                result = json.loads(get_kline("HK.00700"))
        assert result.get("source") == "yfinance"

    def test_non_permission_api_error_returns_error_json(self):
        import moomoo as ft
        ctx_mock = _make_ctx_mock(kline_ret=(ft.RET_ERROR, "symbol not found", None))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_kline("HK.00700"))
        assert "error" in result

    def test_ctx_closed_on_error(self):
        import moomoo as ft
        ctx_mock = _make_ctx_mock(kline_ret=(ft.RET_ERROR, "err", None))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            get_kline("HK.00700")
        ctx_mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# get_plate_list — unit tests
# ---------------------------------------------------------------------------

class TestGetPlateList:
    def test_success_returns_plates(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_plate_list("HK"))

        assert result["market"] == "HK"
        assert len(result["plates"]) == 2
        assert result["plates"][0]["plate_name"] == "Technology"

    def test_success_includes_source_moomoo(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_plate_list("HK"))
        assert result.get("source") == "moomoo"

    def test_defaults_to_hk_market(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_plate_list())
        assert result["market"] == "HK"

    def test_unknown_market_falls_back_to_hk(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_plate_list("XX"))
        assert "plates" in result

    def test_api_error_returns_error_with_moomoo_only_source(self):
        import moomoo as ft
        ctx_mock = _make_ctx_mock(plate_list_ret=(ft.RET_ERROR, "error"))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_plate_list("HK"))
        assert "error" in result
        assert result.get("source") == "moomoo_only"

    def test_connection_error_returns_error_with_moomoo_only_source(self):
        with patch.object(moomoo_server, "_quote_ctx", side_effect=ConnectionRefusedError):
            result = json.loads(get_plate_list("HK"))
        assert "error" in result
        assert result.get("source") == "moomoo_only"


# ---------------------------------------------------------------------------
# get_plate_stocks — unit tests
# ---------------------------------------------------------------------------

class TestGetPlateStocks:
    def test_success_returns_stocks(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_plate_stocks("HK.BK1001"))

        assert result["plate_code"] == "HK.BK1001"
        assert len(result["stocks"]) == 3
        assert result["stocks"][0]["code"] == "HK.00700"

    def test_success_includes_source_moomoo(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_plate_stocks("HK.BK1001"))
        assert result.get("source") == "moomoo"

    def test_plate_code_is_uppercased(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            get_plate_stocks("hk.bk1001")
        ctx_mock.get_plate_stock.assert_called_once_with("HK.BK1001")

    def test_api_error_returns_error_with_moomoo_only_source(self):
        import moomoo as ft
        ctx_mock = _make_ctx_mock(plate_stocks_ret=(ft.RET_ERROR, "not found"))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_plate_stocks("HK.BK9999"))
        assert "error" in result
        assert result.get("source") == "moomoo_only"

    def test_connection_error_returns_error_with_moomoo_only_source(self):
        with patch.object(moomoo_server, "_quote_ctx", side_effect=Exception("no OpenD")):
            result = json.loads(get_plate_stocks("HK.BK1001"))
        assert "error" in result
        assert result.get("source") == "moomoo_only"


# ---------------------------------------------------------------------------
# get_plate_for_stock — unit tests
# ---------------------------------------------------------------------------

def _mock_yf_ticker_sector(ticker):
    mock = MagicMock()
    mock.info = {"sector": "Technology", "industry": "Internet Content & Information"}
    return mock


class TestGetPlateForStock:
    def test_success_returns_plates(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_plate_for_stock("HK.00700"))

        assert result["ticker"] == "HK.00700"
        assert len(result["plates"]) == 1
        assert result["plates"][0]["plate_name"] == "Technology"

    def test_success_includes_source_moomoo(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_plate_for_stock("HK.00700"))
        assert result.get("source") == "moomoo"

    def test_auto_prefix_applied(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            get_plate_for_stock("00700")
        ctx_mock.get_owner_plate.assert_called_once_with(["HK.00700"])

    def test_permission_error_falls_back_to_yfinance(self):
        import moomoo as ft
        import yfinance as yf
        ctx_mock = _make_ctx_mock(owner_plate_ret=(ft.RET_ERROR, "No right to get the quote"))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            with patch.object(yf, "Ticker", return_value=_mock_yf_ticker_sector("HK.00700")):
                result = json.loads(get_plate_for_stock("HK.00700"))
        assert result.get("source") == "yfinance"
        assert result["sector"] == "Technology"
        assert "suggested_peers" in result

    def test_connection_error_falls_back_to_yfinance(self):
        import yfinance as yf
        with patch.object(moomoo_server, "_quote_ctx", side_effect=OSError("refused")):
            with patch.object(yf, "Ticker", return_value=_mock_yf_ticker_sector("HK.00700")):
                result = json.loads(get_plate_for_stock("HK.00700"))
        assert result.get("source") == "yfinance"

    def test_non_permission_api_error_returns_error_json(self):
        import moomoo as ft
        ctx_mock = _make_ctx_mock(owner_plate_ret=(ft.RET_ERROR, "symbol not found"))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_plate_for_stock("HK.00700"))
        assert "error" in result


# ---------------------------------------------------------------------------
# get_multi_snapshot — unit tests
# ---------------------------------------------------------------------------

class TestGetMultiSnapshot:
    def test_success_returns_snapshots_wrapper(self):
        multi_df = pd.DataFrame([
            {
                "code": "HK.00700", "name": "Tencent",
                "last_price": 385.2, "change_val": 3.4, "change_rate": 0.89,
                "volume": 12_000_000, "turnover": 4_620_000_000,
                "market_cap": 3_700_000_000_000,
                "pe_ratio": 18.5, "pb_ratio": 3.1,
                "high_price_52weeks": 430.0, "low_price_52weeks": 260.0,
                "dividend_yield": 0.55,
            },
            {
                "code": "HK.09988", "name": "Alibaba",
                "last_price": 82.5, "change_val": -0.5, "change_rate": -0.6,
                "volume": 20_000_000, "turnover": 1_650_000_000,
                "market_cap": 1_800_000_000_000,
                "pe_ratio": 14.2, "pb_ratio": 1.8,
                "high_price_52weeks": 120.0, "low_price_52weeks": 65.0,
                "dividend_yield": 0.0,
            },
        ])
        ctx_mock = _make_ctx_mock(snapshot_ret=(0, multi_df))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_multi_snapshot(["HK.00700", "HK.09988"]))

        assert "snapshots" in result
        assert result.get("source") == "moomoo"
        assert len(result["snapshots"]) == 2
        tickers = {r["ticker"] for r in result["snapshots"]}
        assert tickers == {"HK.00700", "HK.09988"}

    def test_each_record_has_required_keys(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_multi_snapshot(["HK.00700"]))
        required = {"ticker", "name", "last_price", "change_rate", "pe_ratio", "pb_ratio"}
        assert required.issubset(result["snapshots"][0].keys())

    def test_each_snapshot_record_has_source_field(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_multi_snapshot(["HK.00700"]))
        assert result["snapshots"][0].get("source") == "moomoo"

    def test_empty_list_returns_error_json(self):
        result = json.loads(get_multi_snapshot([]))
        assert "error" in result

    def test_auto_prefix_applied_to_all_tickers(self):
        ctx_mock = _make_ctx_mock()
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            get_multi_snapshot(["00700", "09988"])
        ctx_mock.get_market_snapshot.assert_called_once_with(["HK.00700", "HK.09988"])

    def test_permission_error_falls_back_to_yfinance(self):
        import moomoo as ft
        import yfinance as yf
        ctx_mock = _make_ctx_mock(snapshot_ret=(ft.RET_ERROR, "No right to get the quote"))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            with patch.object(yf, "Ticker", return_value=_mock_yf_info("HK.00700")):
                result = json.loads(get_multi_snapshot(["HK.00700"]))
        assert result.get("source") == "yfinance"
        assert len(result["snapshots"]) == 1

    def test_connection_error_falls_back_to_yfinance(self):
        import yfinance as yf
        with patch.object(moomoo_server, "_quote_ctx", side_effect=Exception("OpenD down")):
            with patch.object(yf, "Ticker", return_value=_mock_yf_info("HK.00700")):
                result = json.loads(get_multi_snapshot(["HK.00700"]))
        assert result.get("source") == "yfinance"

    def test_non_permission_api_error_returns_error_json(self):
        import moomoo as ft
        ctx_mock = _make_ctx_mock(snapshot_ret=(ft.RET_ERROR, "symbol not found"))
        with patch.object(moomoo_server, "_quote_ctx", return_value=ctx_mock):
            result = json.loads(get_multi_snapshot(["HK.00700"]))
        assert "error" in result


# ---------------------------------------------------------------------------
# Integration tests — require real OpenD at 127.0.0.1:11111
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestIntegration:
    """
    These tests hit the real OpenD gateway.  Run with:
        pytest tests/test_moomoo_server.py -m integration
    """

    TICKER = "HK.00700"   # Tencent — confirmed working with HK LV1

    def test_get_snapshot_real(self):
        result = json.loads(get_snapshot(self.TICKER))
        assert "error" not in result, f"OpenD error: {result.get('error')}"
        assert result["ticker"] == self.TICKER
        assert isinstance(result["last_price"], (int, float))
        assert result["last_price"] > 0

    def test_get_kline_real(self):
        result = json.loads(get_kline(self.TICKER, days=10, kline_type="K_DAY"))
        assert "error" not in result, f"OpenD error: {result.get('error')}"
        assert result["ticker"] == self.TICKER
        assert len(result["records"]) > 0
        first = result["records"][0]
        for field in ("open", "close", "high", "low", "volume"):
            assert field in first, f"Missing field: {field}"

    def test_get_plate_list_hk_real(self):
        result = json.loads(get_plate_list("HK"))
        assert "error" not in result, f"OpenD error: {result.get('error')}"
        assert result["market"] == "HK"
        assert len(result["plates"]) > 0

    def test_get_plate_for_stock_real(self):
        result = json.loads(get_plate_for_stock(self.TICKER))
        assert "error" not in result, f"OpenD error: {result.get('error')}"
        assert result["ticker"] == self.TICKER
        assert len(result["plates"]) > 0

    def test_get_plate_stocks_real(self):
        # First get a valid plate code from the plate-for-stock call
        plates_result = json.loads(get_plate_for_stock(self.TICKER))
        assert "error" not in plates_result
        plate_code = plates_result["plates"][0]["plate_code"]

        result = json.loads(get_plate_stocks(plate_code))
        assert "error" not in result, f"OpenD error: {result.get('error')}"
        codes = [s["code"] for s in result["stocks"]]
        assert self.TICKER in codes

    def test_get_multi_snapshot_real(self):
        peers = ["HK.00700", "HK.09988", "HK.00005"]  # Tencent, Alibaba, HSBC
        result = json.loads(get_multi_snapshot(peers))
        assert isinstance(result, list)
        assert len(result) == len(peers)
        for snap in result:
            assert "error" not in snap
            assert snap["last_price"] is not None
