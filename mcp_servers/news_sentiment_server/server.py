"""
MCP Server: news_sentiment_server

Fetches recent news for a stock ticker and scores sentiment using keyword matching.
No external NLP library required — pure Python keyword scoring.

Tools exposed:
  - get_news        : Fetch recent news articles via yfinance
  - score_sentiment : Score a list of articles by title keyword analysis
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import yfinance as yf
from mcp.server.fastmcp import FastMCP

from src.sector_mapper import moomoo_to_yfinance

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("news_sentiment_server")

# ---------------------------------------------------------------------------
# MCP app
# ---------------------------------------------------------------------------
mcp = FastMCP("news_sentiment_server")

# ---------------------------------------------------------------------------
# Sentiment lexicon
# ---------------------------------------------------------------------------

_POSITIVE = {
    "surge", "surges", "surged", "surging",
    "rally", "rallies", "rallied", "rallying",
    "beat", "beats", "beaten",
    "upgrade", "upgraded", "upgrades",
    "outperform", "outperforms", "outperformed",
    "growth", "grow", "grows", "grew", "growing",
    "profit", "profits", "profitable", "profitability",
    "record", "records",
    "bullish", "bull",
    "gain", "gains", "gained",
    "rise", "rises", "rose", "rising",
    "high", "higher", "highest",
    "boost", "boosted", "boosts",
    "strong", "strength",
    "expand", "expands", "expansion",
    "buy", "overweight",
    "dividend", "dividends",
    "revenue", "revenues",     # neutral but slightly positive when mentioned in news
    "innovation", "innovate",
    "partner", "partnership", "deal",
    "approval", "approved",
}

_NEGATIVE = {
    "crash", "crashes", "crashed", "crashing",
    "drop", "drops", "dropped", "dropping",
    "fall", "falls", "fell", "falling",
    "miss", "misses", "missed",
    "downgrade", "downgraded", "downgrades",
    "loss", "losses",
    "bearish", "bear",
    "decline", "declines", "declined", "declining",
    "cut", "cuts",
    "lawsuit", "lawsuits", "sue", "sued", "suing",
    "investigation", "investigate", "investigated",
    "fraud", "scandal",
    "warning", "warn", "warns",
    "risk", "risks", "risky",
    "concern", "concerns",
    "weak", "weakness",
    "layoff", "layoffs",
    "bankruptcy", "bankrupt",
    "penalty", "penalties", "fine", "fines",
    "sell", "underweight",
    "debt", "default",
    "volatile", "volatility",
    "plunge", "plunges", "plunged",
    "tumble", "tumbles", "tumbled",
    "slump", "slumps", "slumped",
}

_STRONG_POS = {"surge", "surges", "surged", "record", "beat", "beats", "bullish", "upgrade", "upgraded"}
_STRONG_NEG = {"crash", "crashes", "fraud", "scandal", "bankruptcy", "bankrupt", "investigation", "lawsuit"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_yf(ticker: str) -> str:
    """Convert MooMoo-format ticker to yfinance format."""
    ticker = ticker.strip()
    if "." in ticker and ticker.split(".")[0].upper() in ("HK", "US", "CN"):
        return moomoo_to_yfinance(ticker)
    return ticker


def _score_title(title: str) -> float:
    """
    Score a single news title on [-1, +1].

    Method:
    - Tokenise by splitting on non-word characters, lowercase.
    - Count positive and negative keyword hits.
    - Strong keywords count double.
    - score = (pos - neg) / max(pos + neg, 1), clamped to [-1, +1].
    """
    if not title:
        return 0.0
    words = set(re.split(r"\W+", title.lower()))
    pos = sum(2 if w in _STRONG_POS else 1 for w in words if w in _POSITIVE)
    neg = sum(2 if w in _STRONG_NEG else 1 for w in words if w in _NEGATIVE)
    total = pos + neg
    if total == 0:
        return 0.0
    return round(max(-1.0, min(1.0, (pos - neg) / total)), 4)


def _label(score: float) -> str:
    if score >= 0.3:
        return "Positive"
    if score <= -0.3:
        return "Negative"
    return "Neutral"


def _ts_to_iso(ts: Any) -> str:
    """Convert a UNIX timestamp (int/float) to ISO date string."""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return str(ts)


# ---------------------------------------------------------------------------
# Tool: get_news
# ---------------------------------------------------------------------------

@mcp.tool()
def get_news(ticker: str, days: int = 7) -> str:
    """
    Fetch recent news articles for a stock ticker using yfinance.

    Args:
        ticker: Ticker in MooMoo format ("HK.00700", "US.AAPL") or yfinance
                format ("0700.HK", "AAPL").
        days:   Maximum age of articles in calendar days (default 7).
                Note: yfinance does not filter by date server-side; this
                parameter filters the returned list.

    Returns JSON object:
        {
          "ticker": str,
          "yf_ticker": str,
          "article_count": int,
          "articles": [
            {
              "title": str,
              "publisher": str,
              "link": str,
              "date": str (YYYY-MM-DD),
              "sentiment": float   # pre-scored for convenience
            },
            ...
          ]
        }
    """
    yf_code = _to_yf(ticker)
    logger.info("get_news: %s (yf: %s)  days=%d", ticker, yf_code, days)

    try:
        raw_news = yf.Ticker(yf_code).news or []
    except Exception as exc:
        logger.exception("yfinance error fetching news")
        return json.dumps({"error": f"yfinance error: {exc}"})

    if not raw_news:
        return json.dumps({
            "ticker": ticker,
            "yf_ticker": yf_code,
            "article_count": 0,
            "articles": [],
        })

    # Filter by age
    cutoff_dt = datetime.now(tz=timezone.utc) - __import__("datetime").timedelta(days=days)

    def _parse_news_item(item: dict):
        """Parse a yfinance news item in either old or new API format."""
        content = item.get("content")
        if isinstance(content, dict):
            # New format (yfinance 0.2.50+): {"id": ..., "content": {...}}
            title  = content.get("title", "")
            publisher = (content.get("provider") or {}).get("displayName", "")
            link   = ((content.get("canonicalUrl") or content.get("clickThroughUrl")) or {}).get("url", "")
            pub_date_str = content.get("pubDate", "")
            try:
                pub_dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pub_dt = None
        else:
            # Old format: {"title": ..., "publisher": ..., "providerPublishTime": <ts>}
            title     = item.get("title", "")
            publisher = item.get("publisher", "")
            link      = item.get("link", "")
            ts = item.get("providerPublishTime") or item.get("publishTime") or 0
            pub_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None

        if not title:
            return None
        if pub_dt and pub_dt < cutoff_dt:
            return None
        date_str = pub_dt.strftime("%Y-%m-%d") if pub_dt else ""
        return {"title": title, "publisher": publisher, "link": link,
                "date": date_str, "sentiment": _score_title(title)}

    articles = []
    for item in raw_news:
        parsed = _parse_news_item(item)
        if parsed:
            articles.append(parsed)

    return json.dumps({
        "ticker": ticker,
        "yf_ticker": yf_code,
        "article_count": len(articles),
        "articles": articles,
    })


# ---------------------------------------------------------------------------
# Tool: score_sentiment
# ---------------------------------------------------------------------------

@mcp.tool()
def score_sentiment(articles_json: str) -> str:
    """
    Score sentiment for a list of news articles by keyword analysis.

    Accepts either:
    - A JSON string that is the full get_news response (with "articles" key), or
    - A JSON string that is a bare list of article dicts.

    Each article is scored on its "title" field.

    Returns:
        {
          "article_count": int,
          "overall_score": float,     # mean of individual scores, [-1, +1]
          "overall_label": str,       # "Positive" | "Neutral" | "Negative"
          "articles": [
            {"title": str, "sentiment": float, "label": str},
            ...
          ]
        }
    """
    logger.info("score_sentiment: scoring article batch")

    try:
        parsed = json.loads(articles_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid JSON: {exc}"})

    # Accept either full get_news response or bare list
    if isinstance(parsed, dict):
        articles = parsed.get("articles", [])
    elif isinstance(parsed, list):
        articles = parsed
    else:
        return json.dumps({"error": "articles_json must be a JSON object or array"})

    if not articles:
        return json.dumps({
            "article_count": 0,
            "overall_score": 0.0,
            "overall_label": "Neutral",
            "articles": [],
        })

    scored = []
    for art in articles:
        title = art.get("title", "")
        score = _score_title(title)
        scored.append({
            "title":     title,
            "publisher": art.get("publisher", ""),
            "date":      art.get("date", ""),
            "link":      art.get("link", ""),
            "sentiment": score,
            "label":     _label(score),
        })

    scores = [s["sentiment"] for s in scored]
    overall = round(sum(scores) / len(scores), 4) if scores else 0.0

    return json.dumps({
        "article_count": len(scored),
        "overall_score": overall,
        "overall_label": _label(overall),
        "articles": scored,
    })


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting news_sentiment_server MCP")
    mcp.run()
