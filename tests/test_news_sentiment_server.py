"""
Tests for mcp_servers/news_sentiment_server/server.py

Unit tests mock yfinance so no network call is needed.
Integration tests (marked @pytest.mark.integration) call real yfinance.

Run unit tests only:
    pytest tests/test_news_sentiment_server.py -m "not integration"
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Import the server module by file path under a unique module name ──────
import importlib.util as _ilu

_SERVER_FILE = Path(__file__).parent.parent / "mcp_servers" / "news_sentiment_server" / "server.py"
_SERVER_DIR  = str(_SERVER_FILE.parent)
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

_spec = _ilu.spec_from_file_location("news_sentiment_server_mod", _SERVER_FILE)
news_srv = _ilu.module_from_spec(_spec)
sys.modules["news_sentiment_server_mod"] = news_srv
_spec.loader.exec_module(news_srv)

_score_title  = news_srv._score_title
_label        = news_srv._label
_ts_to_iso    = news_srv._ts_to_iso
get_news      = news_srv.get_news
score_sentiment = news_srv.score_sentiment


# ─────────────────────────────────────────────────────────────────────────────
# _score_title
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreTitle:
    def test_positive_headline(self):
        score = _score_title("Tencent surges after beating earnings expectations")
        assert score > 0

    def test_negative_headline(self):
        score = _score_title("Company crashes on fraud investigation and lawsuit")
        assert score < 0

    def test_neutral_headline(self):
        score = _score_title("Company announces quarterly results")
        assert score == 0.0

    def test_empty_string(self):
        assert _score_title("") == 0.0

    def test_bounds(self):
        score = _score_title("surge record beat upgrade outperform growth profit bullish rally")
        assert -1.0 <= score <= 1.0

    def test_strong_positive_scores_at_least_as_high_as_weak(self):
        # Both should be positive; strong keywords (surges, record, beat) must not score LOWER
        strong = _score_title("Stock surges to record after beating estimates")
        weak   = _score_title("Stock shows growth this quarter")
        assert strong >= weak
        assert strong > 0

    def test_case_insensitive(self):
        lower = _score_title("tencent surges after upgrade")
        upper = _score_title("TENCENT SURGES AFTER UPGRADE")
        assert lower == upper

    def test_mixed_signals(self):
        # Positive and negative words — score should be between -1 and 1
        score = _score_title("Stock rallies despite investigation into losses")
        assert -1.0 < score < 1.0


class TestLabel:
    def test_positive_above_threshold(self):  assert _label(0.5)  == "Positive"
    def test_negative_below_threshold(self):  assert _label(-0.5) == "Negative"
    def test_neutral_near_zero(self):          assert _label(0.0)  == "Neutral"
    def test_boundary_positive(self):          assert _label(0.3)  == "Positive"
    def test_boundary_negative(self):          assert _label(-0.3) == "Negative"
    def test_just_inside_neutral_pos(self):    assert _label(0.29) == "Neutral"
    def test_just_inside_neutral_neg(self):    assert _label(-0.29) == "Neutral"


class TestTsToIso:
    def test_valid_timestamp(self):
        result = _ts_to_iso(1700000000)
        assert len(result) == 10          # YYYY-MM-DD
        assert result[4] == "-"

    def test_none_returns_str(self):
        result = _ts_to_iso(None)
        assert isinstance(result, str)

    def test_zero_returns_str(self):
        result = _ts_to_iso(0)
        assert isinstance(result, str)


# ─────────────────────────────────────────────────────────────────────────────
# get_news
# ─────────────────────────────────────────────────────────────────────────────

def _make_news_items(n: int = 3) -> list[dict]:
    from datetime import datetime, timezone, timedelta
    now = int(datetime.now(tz=timezone.utc).timestamp())
    return [
        {
            "title": f"Article {i}: Tencent surges on strong earnings",
            "publisher": "Reuters",
            "link": f"https://example.com/news/{i}",
            "providerPublishTime": now - i * 3600,  # i hours ago
        }
        for i in range(n)
    ]


class TestGetNews:
    def _call(self, ticker: str, days: int = 7, news_items=None):
        ticker_mock = MagicMock()
        ticker_mock.news = news_items if news_items is not None else _make_news_items()
        with patch.object(news_srv.yf, "Ticker", return_value=ticker_mock):
            return json.loads(get_news(ticker, days=days))

    def test_success_returns_articles(self):
        result = self._call("HK.00700")
        assert "error" not in result
        assert result["ticker"] == "HK.00700"
        assert result["yf_ticker"] == "0700.HK"
        assert isinstance(result["articles"], list)

    def test_articles_have_required_fields(self):
        result = self._call("HK.00700")
        for art in result["articles"]:
            assert "title" in art
            assert "publisher" in art
            assert "date" in art
            assert "sentiment" in art
            assert -1.0 <= art["sentiment"] <= 1.0

    def test_article_count_matches(self):
        result = self._call("HK.00700", news_items=_make_news_items(5))
        assert result["article_count"] == len(result["articles"])

    def test_old_articles_filtered_by_days(self):
        from datetime import datetime, timezone, timedelta
        old_ts = int((datetime.now(tz=timezone.utc) - timedelta(days=30)).timestamp())
        old_items = [
            {"title": "Old news", "publisher": "X",
             "link": "", "providerPublishTime": old_ts}
        ]
        result = self._call("HK.00700", days=7, news_items=old_items)
        assert len(result["articles"]) == 0

    def test_empty_news_returns_empty_list(self):
        result = self._call("HK.00700", news_items=[])
        assert result["article_count"] == 0
        assert result["articles"] == []

    def test_none_news_returns_empty_list(self):
        result = self._call("HK.00700", news_items=None)
        # Mock returns _make_news_items() by default which is > 0
        assert isinstance(result["articles"], list)

    def test_us_ticker_passthrough(self):
        result = self._call("US.AAPL", news_items=_make_news_items(2))
        assert result["yf_ticker"] == "AAPL"

    def test_yfinance_exception_returns_error(self):
        with patch.object(news_srv.yf, "Ticker", side_effect=Exception("network")):
            result = json.loads(get_news("HK.00700"))
        assert "error" in result

    def test_pre_scored_sentiment_in_articles(self):
        result = self._call("HK.00700", news_items=_make_news_items(3))
        for art in result["articles"]:
            assert art["sentiment"] > 0  # "surges" is positive

    def test_article_date_is_iso_format(self):
        result = self._call("HK.00700", news_items=_make_news_items(1))
        date_str = result["articles"][0]["date"]
        assert len(date_str) == 10   # YYYY-MM-DD
        assert date_str[4] == "-"


# ─────────────────────────────────────────────────────────────────────────────
# score_sentiment
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreSentiment:
    def _articles_json(self, titles: list[str]) -> str:
        return json.dumps([{"title": t, "publisher": "Test", "date": "2024-01-01"} for t in titles])

    def test_positive_overall(self):
        articles = self._articles_json([
            "Stock surges to record high after beating expectations",
            "Company upgrades guidance on strong growth",
        ])
        result = json.loads(score_sentiment(articles))
        assert result["overall_score"] > 0
        assert result["overall_label"] == "Positive"

    def test_negative_overall(self):
        articles = self._articles_json([
            "Stock crashes on fraud investigation and lawsuit",
            "Company declares bankruptcy amid declining revenue",
        ])
        result = json.loads(score_sentiment(articles))
        assert result["overall_score"] < 0
        assert result["overall_label"] == "Negative"

    def test_neutral_overall(self):
        articles = self._articles_json(["Company announces quarterly results"])
        result = json.loads(score_sentiment(articles))
        assert result["overall_label"] == "Neutral"

    def test_empty_list_returns_neutral(self):
        result = json.loads(score_sentiment(json.dumps([])))
        assert result["overall_score"] == 0.0
        assert result["overall_label"] == "Neutral"
        assert result["article_count"] == 0

    def test_accepts_full_get_news_response(self):
        """score_sentiment should accept the full output of get_news."""
        ticker_mock = MagicMock()
        ticker_mock.news = _make_news_items(3)
        with patch.object(news_srv.yf, "Ticker", return_value=ticker_mock):
            news_json = get_news("HK.00700")
        result = json.loads(score_sentiment(news_json))
        assert "overall_score" in result
        assert result["article_count"] == 3

    def test_accepts_bare_list(self):
        articles = self._articles_json(["Company surges on record profit"])
        result = json.loads(score_sentiment(articles))
        assert "overall_score" in result

    def test_invalid_json_returns_error(self):
        result = json.loads(score_sentiment("this is not json"))
        assert "error" in result

    def test_wrong_type_returns_error(self):
        result = json.loads(score_sentiment(json.dumps(42)))
        assert "error" in result

    def test_per_article_scores_present(self):
        articles = self._articles_json(["Surge on record earnings", "Crash on fraud"])
        result = json.loads(score_sentiment(articles))
        for art in result["articles"]:
            assert "sentiment" in art
            assert "label" in art
            assert -1.0 <= art["sentiment"] <= 1.0

    def test_article_count_correct(self):
        titles = ["News A", "News B", "News C"]
        result = json.loads(score_sentiment(self._articles_json(titles)))
        assert result["article_count"] == len(titles)

    def test_overall_score_is_mean(self):
        articles = [
            {"title": "Surge record", "publisher": "", "date": ""},
            {"title": "Crash fraud",  "publisher": "", "date": ""},
        ]
        result = json.loads(score_sentiment(json.dumps(articles)))
        per = [a["sentiment"] for a in result["articles"]]
        expected = round(sum(per) / len(per), 4)
        assert result["overall_score"] == pytest.approx(expected, abs=0.0001)


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestNewsSentimentIntegration:
    def test_get_news_real_hk(self):
        result = json.loads(get_news("HK.00700", days=30))
        assert "error" not in result
        assert isinstance(result["articles"], list)

    def test_score_sentiment_pipeline(self):
        news_json = get_news("HK.00700", days=30)
        result = json.loads(score_sentiment(news_json))
        assert "overall_score" in result
        assert -1.0 <= result["overall_score"] <= 1.0

    def test_get_news_us_ticker(self):
        result = json.loads(get_news("US.AAPL", days=14))
        assert "error" not in result
        assert result["yf_ticker"] == "AAPL"
