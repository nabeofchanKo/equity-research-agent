"""
End-to-end integration tests for moomoo-dashboard.

All tests are marked @pytest.mark.integration and require:
  - MooMoo OpenD running at 127.0.0.1:11111 with HK LV1 subscription
  - Internet access (for yfinance)

Run:
    pytest tests/test_integration.py -m integration -v
"""

import json
from pathlib import Path

import pytest

# ── Section markers that must appear in a generated report ────────────────
_REQUIRED_SECTIONS = [
    "section-price",
    "section-technicals",
    "section-fundamentals",
    "section-peers",
    "section-performance",
    "section-sentiment",
]

_REQUIRED_CHART_IDS = [
    "chart-price",
    "chart-rsi",
    "chart-macd",
    "chart-stoch",
    "chart-earnings",
    "chart-performance",
    "chart-signal",
    "chart-sentiment",
]

TARGET = "HK.00700"   # Tencent — confirmed working with HK LV1


# ─────────────────────────────────────────────────────────────────────────────
# MooMoo MCP server tools
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestMooMooMcpTools:
    """Verify every moomoo_server tool returns valid data."""

    def setup_method(self):
        import sys
        from pathlib import Path
        srv = Path(__file__).parent.parent / "mcp_servers" / "moomoo_server"
        if str(srv) not in sys.path:
            sys.path.insert(0, str(srv))
        import importlib
        self.srv = importlib.import_module("server")

    def test_get_snapshot(self):
        result = json.loads(self.srv.get_snapshot(TARGET))
        assert "error" not in result
        assert result["ticker"] == TARGET
        assert isinstance(result["last_price"], (int, float))
        assert result["last_price"] > 0

    def test_get_kline(self):
        result = json.loads(self.srv.get_kline(TARGET, days=30))
        assert "error" not in result
        assert len(result["records"]) > 0
        rec = result["records"][0]
        assert all(k in rec for k in ("open", "close", "high", "low"))

    def test_get_kline_full_180_days(self):
        result = json.loads(self.srv.get_kline(TARGET, days=180))
        assert "error" not in result
        # Expect at least 100 trading days in 180 calendar days
        assert len(result["records"]) >= 100

    def test_get_plate_for_stock(self):
        result = json.loads(self.srv.get_plate_for_stock(TARGET))
        assert "error" not in result
        assert len(result["plates"]) > 0

    def test_get_plate_stocks(self):
        plates = json.loads(self.srv.get_plate_for_stock(TARGET))
        plate_code = plates["plates"][0]["plate_code"]
        result = json.loads(self.srv.get_plate_stocks(plate_code))
        assert "error" not in result
        assert len(result["stocks"]) > 0

    def test_get_multi_snapshot(self):
        peers = ["HK.00700", "HK.09988", "HK.00005"]
        result = json.loads(self.srv.get_multi_snapshot(peers))
        assert isinstance(result, list)
        assert len(result) == len(peers)
        for snap in result:
            assert "error" not in snap


# ─────────────────────────────────────────────────────────────────────────────
# Financials server tools
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestFinancialsServerTools:
    """Verify every financials_server tool returns valid data."""

    def setup_method(self):
        import sys
        from pathlib import Path
        srv = Path(__file__).parent.parent / "mcp_servers" / "financials_server"
        if str(srv) not in sys.path:
            sys.path.insert(0, str(srv))
        import importlib
        # reload to pick up fresh path
        import mcp_servers.financials_server  # noqa (ensures importable)
        self.srv = importlib.import_module("server")

    def test_get_fundamentals_hk(self):
        result = json.loads(self.srv.get_fundamentals(TARGET))
        assert "error" not in result
        assert result["yf_ticker"] == "0700.HK"
        assert isinstance(result.get("current_price"), (int, float))

    def test_get_earnings_hk(self):
        result = json.loads(self.srv.get_earnings(TARGET))
        # Earnings may be unavailable for HK; accept either data or empty error
        assert "ticker" in result or "error" in result

    def test_get_performance_hk(self):
        result = json.loads(self.srv.get_performance(TARGET))
        assert "error" not in result
        assert result["benchmark"] == "^HSI"
        assert len(result["performance"]) == 4


# ─────────────────────────────────────────────────────────────────────────────
# News sentiment server tools
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestNewsSentimentServerTools:
    """news_sentiment_server tests — requires internet access for yfinance."""

    def setup_method(self):
        import sys, importlib
        from pathlib import Path
        srv = Path(__file__).parent.parent / "mcp_servers" / "news_sentiment_server"
        if str(srv) not in sys.path:
            sys.path.insert(0, str(srv))
        self.srv = importlib.import_module("server")

    def test_get_news_returns_articles(self):
        result = json.loads(self.srv.get_news(TARGET, days=30))
        assert "error" not in result
        assert "articles" in result
        # May be 0 articles if no recent news, but structure must be correct
        assert isinstance(result["articles"], list)

    def test_score_sentiment_from_get_news(self):
        news_json = self.srv.get_news(TARGET, days=30)
        result = json.loads(self.srv.score_sentiment(news_json))
        assert "error" not in result
        assert "overall_score" in result
        assert -1.0 <= result["overall_score"] <= 1.0
        assert result["overall_label"] in ("Positive", "Neutral", "Negative")

    def test_score_empty_articles(self):
        result = json.loads(self.srv.score_sentiment(json.dumps([])))
        assert result["overall_score"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Technical indicators with real kline data
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestTechnicalIndicatorsReal:
    def test_compute_all_with_real_kline(self):
        import sys, json, importlib, pandas as pd
        from pathlib import Path
        srv = Path(__file__).parent.parent / "mcp_servers" / "moomoo_server"
        if str(srv) not in sys.path:
            sys.path.insert(0, str(srv))
        moomoo_srv = importlib.import_module("server")

        kline = json.loads(moomoo_srv.get_kline(TARGET, days=180))
        assert "error" not in kline

        from src.technical_indicators import compute_all
        df = pd.DataFrame(kline["records"])
        result = compute_all(df)

        assert -1.0 <= result["signal_score"] <= 1.0
        assert result["data_points"] > 0
        assert result["rsi"]["value"] is not None
        assert result["macd"]["macd"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator pipeline
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestOrchestratorPipeline:
    def test_full_pipeline_hk_00700(self, tmp_path):
        from src.orchestrator import run

        path = run(TARGET, output_dir=str(tmp_path))
        assert Path(path).exists(), f"Report file not created: {path}"

        html = Path(path).read_text(encoding="utf-8")
        assert len(html) > 20_000, f"Report too small: {len(html)} bytes"

        for section in _REQUIRED_SECTIONS:
            assert section in html, f"Missing section: {section}"

        for chart_id in _REQUIRED_CHART_IDS:
            assert chart_id in html, f"Missing chart: {chart_id}"

    def test_report_filename_format(self, tmp_path):
        from src.orchestrator import run
        from datetime import date

        path = run(TARGET, output_dir=str(tmp_path))
        filename = Path(path).name
        assert "00700" in filename
        assert date.today().isoformat() in filename

    def test_report_contains_company_name(self, tmp_path):
        from src.orchestrator import run

        path = run(TARGET, output_dir=str(tmp_path))
        html = Path(path).read_text(encoding="utf-8")
        # Tencent should appear somewhere in the report
        assert "Tencent" in html or "TENCENT" in html or "00700" in html

    def test_report_is_self_contained(self, tmp_path):
        """Report must not reference external .css or local .js files."""
        import re
        from src.orchestrator import run

        path = run(TARGET, output_dir=str(tmp_path))
        html = Path(path).read_text(encoding="utf-8")

        local_css = re.findall(r'<link[^>]+href=["\'](?!https?)([^"\']+\.css)', html)
        assert local_css == [], f"Local CSS refs found: {local_css}"

    def test_report_written_to_outputs(self):
        """Integration smoke test that writes to the real outputs/ directory."""
        from src.orchestrator import run

        project_root = Path(__file__).parent.parent
        out_dir = project_root / "outputs"
        path = run(TARGET, output_dir=str(out_dir))
        assert Path(path).exists()
        size_kb = Path(path).stat().st_size / 1024
        assert size_kb > 100, f"Report suspiciously small: {size_kb:.1f} KB"
        print(f"\n✓ Integration report: {path} ({size_kb:.0f} KB)")


# ─────────────────────────────────────────────────────────────────────────────
# Normaliser
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestNormaliser:
    def test_numeric_assumes_hk(self):
        from src.orchestrator import normalise_ticker
        assert normalise_ticker("00700") == "HK.00700"

    def test_alpha_assumes_us(self):
        from src.orchestrator import normalise_ticker
        assert normalise_ticker("AAPL") == "US.AAPL"

    def test_already_prefixed_hk(self):
        from src.orchestrator import normalise_ticker
        assert normalise_ticker("HK.00700") == "HK.00700"

    def test_already_prefixed_us(self):
        from src.orchestrator import normalise_ticker
        assert normalise_ticker("US.AAPL") == "US.AAPL"
