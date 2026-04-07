"""
Tests for src/sector_mapper.py

All tests mock yfinance so no network call is made.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.sector_mapper import (
    get_sector_peers,
    moomoo_to_yfinance,
    yfinance_to_moomoo,
)


# ---------------------------------------------------------------------------
# moomoo_to_yfinance
# ---------------------------------------------------------------------------

class TestMoomooToYfinance:
    def test_hk_5digit_to_4digit(self):
        assert moomoo_to_yfinance("HK.00700") == "0700.HK"

    def test_hk_leading_zeros_stripped_correctly(self):
        assert moomoo_to_yfinance("HK.09988") == "9988.HK"

    def test_hk_small_code(self):
        assert moomoo_to_yfinance("HK.00005") == "0005.HK"

    def test_us_strips_prefix(self):
        assert moomoo_to_yfinance("US.AAPL") == "AAPL"

    def test_us_hyphenated_ticker(self):
        assert moomoo_to_yfinance("US.BRK-B") == "BRK-B"

    def test_lowercase_input_normalised(self):
        assert moomoo_to_yfinance("hk.00700") == "0700.HK"

    def test_no_prefix_returns_as_is(self):
        # Assumed to be a US yfinance ticker already
        assert moomoo_to_yfinance("AAPL") == "AAPL"

    def test_whitespace_stripped(self):
        assert moomoo_to_yfinance("  HK.00700  ") == "0700.HK"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            moomoo_to_yfinance("")

    def test_unknown_market_prefix(self):
        # Should not crash — return code.MARKET
        result = moomoo_to_yfinance("SG.D05")
        assert "D05" in result


# ---------------------------------------------------------------------------
# yfinance_to_moomoo
# ---------------------------------------------------------------------------

class TestYfinanceToMoomoo:
    def test_hk_4digit_to_5digit(self):
        assert yfinance_to_moomoo("0700.HK") == "HK.00700"

    def test_hk_no_leading_zero_needed(self):
        assert yfinance_to_moomoo("9988.HK") == "HK.09988"

    def test_hk_small_code(self):
        assert yfinance_to_moomoo("0005.HK") == "HK.00005"

    def test_us_plain_ticker(self):
        assert yfinance_to_moomoo("AAPL") == "US.AAPL"

    def test_us_hyphenated(self):
        assert yfinance_to_moomoo("BRK-B") == "US.BRK-B"

    def test_whitespace_stripped(self):
        assert yfinance_to_moomoo("  0700.HK  ") == "HK.00700"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            yfinance_to_moomoo("")

    def test_unsupported_suffix_raises(self):
        with pytest.raises(ValueError):
            yfinance_to_moomoo("600519.SS")


# ---------------------------------------------------------------------------
# Round-trip consistency
# ---------------------------------------------------------------------------

class TestRoundTrip:
    @pytest.mark.parametrize("moomoo_fmt", [
        "HK.00700", "HK.09988", "HK.00005", "HK.03690",
        "US.AAPL", "US.MSFT", "US.NVDA",
    ])
    def test_moomoo_to_yf_to_moomoo(self, moomoo_fmt: str):
        yf = moomoo_to_yfinance(moomoo_fmt)
        back = yfinance_to_moomoo(yf)
        assert back == moomoo_fmt


# ---------------------------------------------------------------------------
# get_sector_peers
# ---------------------------------------------------------------------------

def _make_yf_mock(sector: str | None):
    ticker_mock = MagicMock()
    ticker_mock.info = {"sector": sector} if sector else {}
    return ticker_mock


class TestGetSectorPeers:
    def test_hk_tech_returns_peers(self):
        with patch("src.sector_mapper.yf.Ticker", return_value=_make_yf_mock("Technology")):
            peers = get_sector_peers("0700.HK", max_peers=5)
        assert isinstance(peers, list)
        assert len(peers) <= 5
        assert "0700.HK" not in peers  # self excluded by default

    def test_us_tech_returns_peers(self):
        with patch("src.sector_mapper.yf.Ticker", return_value=_make_yf_mock("Technology")):
            peers = get_sector_peers("AAPL", max_peers=5)
        assert "AAPL" not in peers
        assert len(peers) <= 5

    def test_include_self_true(self):
        with patch("src.sector_mapper.yf.Ticker", return_value=_make_yf_mock("Technology")):
            peers = get_sector_peers("0700.HK", max_peers=10, include_self=True)
        assert "0700.HK" in peers

    def test_max_peers_respected(self):
        with patch("src.sector_mapper.yf.Ticker", return_value=_make_yf_mock("Technology")):
            peers = get_sector_peers("0700.HK", max_peers=3)
        assert len(peers) <= 3

    def test_no_sector_returns_empty(self):
        with patch("src.sector_mapper.yf.Ticker", return_value=_make_yf_mock(None)):
            peers = get_sector_peers("0700.HK")
        assert peers == []

    def test_unknown_sector_returns_empty(self):
        with patch("src.sector_mapper.yf.Ticker", return_value=_make_yf_mock("Alien Sector")):
            peers = get_sector_peers("0700.HK")
        assert peers == []

    def test_yfinance_exception_returns_empty(self):
        with patch("src.sector_mapper.yf.Ticker", side_effect=Exception("network error")):
            peers = get_sector_peers("0700.HK")
        assert peers == []

    def test_hk_and_us_use_different_peer_maps(self):
        with patch("src.sector_mapper.yf.Ticker", return_value=_make_yf_mock("Technology")):
            hk_peers = get_sector_peers("0700.HK", max_peers=20, include_self=True)
            us_peers = get_sector_peers("AAPL", max_peers=20, include_self=True)
        # HK peers should contain .HK suffixes; US peers should not
        assert all(".HK" in p for p in hk_peers)
        assert all(".HK" not in p for p in us_peers)

    def test_all_returned_tickers_are_strings(self):
        with patch("src.sector_mapper.yf.Ticker", return_value=_make_yf_mock("Financial Services")):
            peers = get_sector_peers("0005.HK")
        assert all(isinstance(p, str) for p in peers)
