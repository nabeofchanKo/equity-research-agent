"""
Orchestrator for moomoo-dashboard report generation.

Collects data from MooMoo OpenD and yfinance directly (no MCP required),
runs technical analysis, and generates the HTML report.

MooMoo OpenD is the primary source for snapshot and K-line data.  When
MooMoo returns a permission error ("No right") or is not reachable, the
orchestrator automatically falls back to yfinance for those data points and
logs a warning.

Usage:
    python -m src.orchestrator HK.00700
    python -m src.orchestrator US.AAPL
    python -m src.orchestrator NVDA          # assumes US
    python -m src.orchestrator 00700         # assumes HK
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

# ── ensure project root is on sys.path when run as a module ────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.report_generator import generate_report
from src.sector_mapper import moomoo_to_yfinance
from src.technical_indicators import compute_all
from src.utils import load_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("orchestrator")

# ---------------------------------------------------------------------------
# Ticker normalisation
# ---------------------------------------------------------------------------

def normalise_ticker(raw: str) -> str:
    """
    Normalise any ticker format to MooMoo format (MARKET.CODE).

    Examples:
        00700   → HK.00700
        0700.HK → HK.00700   (yfinance format)
        AAPL    → US.AAPL
        US.AAPL → US.AAPL
    """
    t = raw.strip().upper()
    if "." not in t:
        return f"HK.{t}" if t.isnumeric() else f"US.{t}"
    market, code = t.split(".", 1)
    if market in ("HK", "US", "CN"):
        return t                        # already MooMoo format
    if code in ("HK",):
        # yfinance format like 0700.HK
        from src.sector_mapper import yfinance_to_moomoo
        return yfinance_to_moomoo(t)
    return t


# Error substrings that indicate a MooMoo permission/access failure
_MOOMOO_PERM_ERRORS = (
    "no right",
    "no permission",
    "permission",
    "quota",
    "subscription",
)


def _is_moomoo_perm_error(msg: str) -> bool:
    lower = str(msg).lower()
    return any(t in lower for t in _MOOMOO_PERM_ERRORS)


# ---------------------------------------------------------------------------
# MooMoo data collection
# ---------------------------------------------------------------------------

def _collect_moomoo(ticker: str, cfg: dict) -> dict:
    """
    Collect snapshot and K-line data directly from MooMoo OpenD.
    Returns dict with keys: snapshot, kline_records.
    Raises RuntimeError if OpenD is unreachable or returns a non-permission error.
    Raises PermissionError (subclass of RuntimeError) for access/right errors
    so the caller can choose to fall back to yfinance.
    """
    import moomoo as ft

    host = cfg.get("moomoo", {}).get("host", "127.0.0.1")
    port = int(cfg.get("moomoo", {}).get("port", 11111))
    days = int(cfg.get("moomoo", {}).get("default_kline_days", 180))

    logger.info("Connecting to OpenD at %s:%d", host, port)
    ctx = ft.OpenQuoteContext(host=host, port=port)

    try:
        # ── Snapshot ──────────────────────────────────────────────────────
        ret, data = ctx.get_market_snapshot([ticker])
        if ret != ft.RET_OK:
            msg = str(data)
            if _is_moomoo_perm_error(msg):
                raise PermissionError(f"get_market_snapshot failed: {msg}")
            raise RuntimeError(f"get_market_snapshot failed: {msg}")
        snap_records = json.loads(data.to_json(orient="records", date_format="iso"))
        if not snap_records:
            raise RuntimeError(f"No snapshot data for {ticker}")
        row = snap_records[0]
        snapshot = {
            "ticker":         ticker,
            "name":           row.get("name", ""),
            "last_price":     row.get("last_price"),
            "change_val":     row.get("change_val"),
            "change_rate":    row.get("change_rate"),
            "volume":         row.get("volume"),
            "turnover":       row.get("turnover"),
            "market_cap":     row.get("market_cap"),
            "pe_ratio":       row.get("pe_ratio"),
            "pb_ratio":       row.get("pb_ratio"),
            "52w_high":       row.get("high_price_52weeks"),
            "52w_low":        row.get("low_price_52weeks"),
            "dividend_yield": row.get("dividend_yield"),
            "source":         "moomoo",
        }

        # ── K-line ────────────────────────────────────────────────────────
        from datetime import date, timedelta
        end_date   = date.today()
        start_date = end_date - timedelta(days=days)
        fields = [
            ft.KL_FIELD.DATE_TIME, ft.KL_FIELD.OPEN,  ft.KL_FIELD.CLOSE,
            ft.KL_FIELD.HIGH,      ft.KL_FIELD.LOW,   ft.KL_FIELD.TRADE_VOL,
            ft.KL_FIELD.TRADE_VAL, ft.KL_FIELD.CHANGE_RATE, ft.KL_FIELD.LAST_CLOSE,
            ft.KL_FIELD.PE_RATIO,
        ]
        ret2, kdata, _ = ctx.get_history_kline(
            ticker,
            start=str(start_date), end=str(end_date),
            ktype=ft.KLType.K_DAY, autype=ft.AuType.QFQ,
            fields=fields, max_count=1000,
        )
        if ret2 != ft.RET_OK:
            msg2 = str(kdata)
            if _is_moomoo_perm_error(msg2):
                raise PermissionError(f"get_history_kline failed: {msg2}")
            logger.warning("get_history_kline failed: %s — continuing without K-line", msg2)
            kline_records = []
        else:
            kline_records = json.loads(kdata.to_json(orient="records", date_format="iso"))

    finally:
        ctx.close()

    return {"snapshot": snapshot, "kline_records": kline_records, "source": "moomoo"}


def _collect_moomoo_yf(ticker: str, cfg: dict) -> dict:
    """
    yfinance fallback for snapshot + K-line when MooMoo is unavailable.
    Returns same dict shape as _collect_moomoo with source="yfinance".
    """
    import yfinance as yf
    from datetime import date, timedelta

    days     = int(cfg.get("moomoo", {}).get("default_kline_days", 180))
    yf_code  = moomoo_to_yfinance(ticker)
    logger.info("yfinance fallback: fetching snapshot+kline for %s (yf: %s)", ticker, yf_code)

    info = yf.Ticker(yf_code).info
    price      = info.get("currentPrice") or info.get("regularMarketPrice")
    prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
    change_val  = (price - prev_close) if (price and prev_close) else None
    change_rate = (change_val / prev_close * 100) if (change_val and prev_close) else None

    snapshot = {
        "ticker":         ticker,
        "name":           info.get("longName") or info.get("shortName", ""),
        "last_price":     price,
        "change_val":     change_val,
        "change_rate":    change_rate,
        "volume":         info.get("regularMarketVolume") or info.get("volume"),
        "turnover":       None,
        "market_cap":     info.get("marketCap"),
        "pe_ratio":       info.get("trailingPE"),
        "pb_ratio":       info.get("priceToBook"),
        "52w_high":       info.get("fiftyTwoWeekHigh"),
        "52w_low":        info.get("fiftyTwoWeekLow"),
        "dividend_yield": info.get("dividendYield"),
        "source":         "yfinance",
    }

    end_date   = date.today()
    start_date = end_date - timedelta(days=days)
    hist = yf.download(
        yf_code,
        start=str(start_date), end=str(end_date),
        auto_adjust=True, progress=False,
    )
    kline_records = []
    if not hist.empty:
        if hasattr(hist.columns, "levels"):
            hist.columns = hist.columns.get_level_values(0)
        for ts, row in hist.iterrows():
            kline_records.append({
                "time_key":    str(ts.date()) + " 00:00:00",
                "open":        float(row["Open"]),
                "high":        float(row["High"]),
                "low":         float(row["Low"]),
                "close":       float(row["Close"]),
                "volume":      int(row["Volume"]),
                "turnover":    None,
                "change_rate": None,
                "last_close":  None,
                "pe_ratio":    None,
            })

    return {"snapshot": snapshot, "kline_records": kline_records, "source": "yfinance"}


# ---------------------------------------------------------------------------
# Financials data collection
# ---------------------------------------------------------------------------

def _collect_financials(ticker: str) -> dict:
    """
    Collect fundamentals, earnings, peer comparison, and performance via yfinance.
    Returns dict with keys: fundamentals, earnings, peers, performance.
    """
    import yfinance as yf
    from src.sector_mapper import get_sector_peers

    yf_code = moomoo_to_yfinance(ticker)
    logger.info("Fetching financials for %s (yf: %s)", ticker, yf_code)

    # ── Fundamentals ────────────────────────────────────────────────────────
    try:
        info = yf.Ticker(yf_code).info
    except Exception as exc:
        logger.warning("yfinance info failed: %s", exc)
        info = {}

    def _safe(v: Any) -> Any:
        if v is None: return None
        try:
            import math
            if math.isnan(float(v)): return None
        except (TypeError, ValueError):
            pass
        return v

    def _r(v: Any, n: int = 4) -> Any:
        s = _safe(v)
        return round(float(s), n) if s is not None else None

    fundamentals = {
        "ticker": ticker, "yf_ticker": yf_code,
        "name":         _safe(info.get("longName") or info.get("shortName")),
        "sector":       _safe(info.get("sector")),
        "industry":     _safe(info.get("industry")),
        "market_cap":   _safe(info.get("marketCap")),
        "currency":     _safe(info.get("currency")),
        "current_price":_r(info.get("currentPrice") or info.get("regularMarketPrice"), 3),
        "pe_ratio":     _r(info.get("trailingPE")),
        "forward_pe":   _r(info.get("forwardPE")),
        "pb_ratio":     _r(info.get("priceToBook")),
        "roe":          _r(info.get("returnOnEquity")),
        "roa":          _r(info.get("returnOnAssets")),
        "eps_ttm":      _r(info.get("trailingEps"), 3),
        "eps_forward":  _r(info.get("forwardEps"), 3),
        "revenue_ttm":  _safe(info.get("totalRevenue")),
        "net_income_ttm":_safe(info.get("netIncomeToCommon")),
        "profit_margin":_r(info.get("profitMargins")),
        "dividend_yield":_r(info.get("dividendYield")),
        "beta":         _r(info.get("beta"), 3),
        "52w_high":     _r(info.get("fiftyTwoWeekHigh"), 3),
        "52w_low":      _r(info.get("fiftyTwoWeekLow"), 3),
        "book_value":   _r(info.get("bookValue"), 3),
        "debt_to_equity":_r(info.get("debtToEquity"), 2),
        "current_ratio":_r(info.get("currentRatio"), 2),
        "gross_margin": _r(info.get("grossMargins")),
        "operating_margin":_r(info.get("operatingMargins")),
        "analyst_target":_r(info.get("targetMeanPrice"), 3),
        "recommendation":_safe(info.get("recommendationKey")),
    }

    # ── Earnings ─────────────────────────────────────────────────────────────
    quarters: list[dict] = []
    try:
        t = yf.Ticker(yf_code)
        qf = t.quarterly_financials
        if qf is not None and not qf.empty:
            for col in list(qf.columns)[:4]:
                period_str = str(col.date()) if hasattr(col, "date") else str(col)
                row: dict = {"period": period_str}
                for idx in qf.index:
                    if "total revenue" in str(idx).lower():
                        row["revenue"] = _safe(qf.loc[idx, col])
                    if "net income" in str(idx).lower():
                        row["net_income"] = _safe(qf.loc[idx, col])
                    if "gross profit" in str(idx).lower():
                        row["gross_profit"] = _safe(qf.loc[idx, col])
                quarters.append(row)
    except Exception as exc:
        logger.warning("Earnings collection failed: %s", exc)
    earnings = {"ticker": ticker, "quarters": quarters}

    # ── Peer comparison ───────────────────────────────────────────────────────
    from datetime import date as _date
    year_start = _date(_date.today().year, 1, 1)
    peer_yf = get_sector_peers(yf_code, max_peers=8, include_self=False)
    peer_rows: list[dict] = []
    all_codes = [yf_code] + peer_yf
    for code in all_codes:
        try:
            pi = yf.Ticker(code).info
            ytd_ret = None
            try:
                hist = yf.Ticker(code).history(start=str(year_start), auto_adjust=True)
                if not hist.empty and len(hist) >= 2:
                    ytd_ret = round((hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100, 2)
            except Exception:
                pass
            peer_rows.append({
                "ticker":         code,
                "is_target":      code == yf_code,
                "name":           _safe(pi.get("longName") or pi.get("shortName")),
                "sector":         _safe(pi.get("sector")),
                "market_cap":     _safe(pi.get("marketCap")),
                "current_price":  _r(pi.get("currentPrice") or pi.get("regularMarketPrice"), 3),
                "pe_ratio":       _r(pi.get("trailingPE")),
                "pb_ratio":       _r(pi.get("priceToBook")),
                "roe":            _r(pi.get("returnOnEquity")),
                "eps_ttm":        _r(pi.get("trailingEps"), 3),
                "dividend_yield": _r(pi.get("dividendYield")),
                "beta":           _r(pi.get("beta"), 3),
                "ytd_return_pct": ytd_ret,
                "recommendation": _safe(pi.get("recommendationKey")),
            })
        except Exception as exc:
            logger.warning("Peer data for %s failed: %s", code, exc)

    numeric_cols = ["pe_ratio", "pb_ratio", "roe", "eps_ttm", "dividend_yield", "ytd_return_pct"]
    averages: dict = {}
    for col in numeric_cols:
        vals = [r[col] for r in peer_rows if r.get(col) is not None]
        averages[col] = round(sum(vals) / len(vals), 4) if vals else None

    peers = {"ticker": ticker, "yf_ticker": yf_code, "peers": peer_rows, "sector_averages": averages}

    # ── Performance ───────────────────────────────────────────────────────────
    import pandas as pd
    from datetime import timedelta as _td
    bench = "^HSI" if yf_code.endswith(".HK") else "SPY"
    today = _date.today()
    perf_rows: list[dict] = []
    try:
        raw = yf.download([yf_code, bench], start=str(today - _td(days=380)),
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
        else:
            close = raw[["Close"]].rename(columns={"Close": yf_code})

        for label, days in [("1M", 30), ("3M", 90), ("6M", 180), ("1Y", 365)]:
            cutoff = today - _td(days=days)

            def _ret(col: str) -> Optional[float]:
                if col not in close.columns:
                    return None
                s = close[col].dropna()
                s = s[s.index.date >= cutoff]
                if len(s) < 2:
                    return None
                return round((float(s.iloc[-1]) / float(s.iloc[0]) - 1) * 100, 2)

            t_ret = _ret(yf_code)
            b_ret = _ret(bench)
            perf_rows.append({
                "period": label, "days": days,
                "ticker_return_pct": t_ret,
                "benchmark_return_pct": b_ret,
                "alpha_pct": round(t_ret - b_ret, 2) if (t_ret is not None and b_ret is not None) else None,
            })
    except Exception as exc:
        logger.warning("Performance collection failed: %s", exc)

    performance = {"ticker": ticker, "yf_ticker": yf_code, "benchmark": bench, "performance": perf_rows}

    return {"fundamentals": fundamentals, "earnings": earnings, "peers": peers, "performance": performance}


# ---------------------------------------------------------------------------
# News & sentiment collection
# ---------------------------------------------------------------------------

def _collect_news(ticker: str, days: int = 7) -> Optional[dict]:
    """
    Fetch and score news. Returns None on any error.
    """
    import yfinance as yf
    yf_code = moomoo_to_yfinance(ticker)
    from datetime import datetime, timezone, timedelta
    import re as _re

    try:
        raw = yf.Ticker(yf_code).news or []
    except Exception as exc:
        logger.warning("News collection failed: %s", exc)
        return None

    if not raw:
        return {"score": 0.0, "label": "Neutral", "articles": []}

    cutoff_dt = datetime.now(tz=timezone.utc) - timedelta(days=days)

    pos_kw = {"surge","surges","surged","rally","rallied","beat","beats","upgrade","upgraded",
               "outperform","growth","profit","record","bullish","gain","rise","high","strong",
               "boost","approval","approved","buy","dividend","innovation","deal"}
    neg_kw = {"crash","crashed","drop","dropped","fall","fell","miss","missed","downgrade","downgraded",
               "loss","losses","bearish","decline","declined","cut","lawsuit","investigation","fraud",
               "scandal","warn","warning","risk","weak","layoff","bankruptcy","penalty","sell",
               "volatile","plunge","tumble","slump"}
    strong_p = {"surge","surged","record","beat","beats","bullish","upgrade","upgraded"}
    strong_n = {"crash","fraud","scandal","bankruptcy","investigation","lawsuit"}

    def _score(title: str) -> float:
        if not title: return 0.0
        words = set(_re.split(r"\W+", title.lower()))
        p = sum(2 if w in strong_p else 1 for w in words if w in pos_kw)
        n = sum(2 if w in strong_n else 1 for w in words if w in neg_kw)
        total = p + n
        return round(max(-1.0, min(1.0, (p - n) / total)), 4) if total else 0.0

    def _parse_item(item: dict) -> Optional[dict]:
        """Parse a yfinance news item — handles both old and new API formats."""
        # New format (yfinance 0.2.50+): item = {"id": ..., "content": {...}}
        content = item.get("content")
        if isinstance(content, dict):
            title  = content.get("title", "")
            source = (content.get("provider") or {}).get("displayName", "")
            url    = ((content.get("canonicalUrl") or content.get("clickThroughUrl")) or {}).get("url", "")
            pub_date_str = content.get("pubDate", "")
            # pubDate is ISO 8601 string like "2026-04-07T19:34:28Z"
            try:
                pub_dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pub_dt = None
        else:
            # Old format: item = {"title": ..., "publisher": ..., "providerPublishTime": <unix ts>}
            title  = item.get("title", "")
            source = item.get("publisher", "")
            url    = item.get("link", "")
            ts = item.get("providerPublishTime") or item.get("publishTime") or 0
            pub_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None

        if not title:
            return None
        if pub_dt and pub_dt < cutoff_dt:
            return None

        date_str = pub_dt.strftime("%Y-%m-%d") if pub_dt else ""
        return {
            "title":     title,
            "source":    source,
            "date":      date_str,
            "url":       url,
            "sentiment": _score(title),
        }

    articles = []
    for item in raw:
        parsed = _parse_item(item)
        if parsed:
            articles.append(parsed)

    overall = round(sum(a["sentiment"] for a in articles) / len(articles), 4) if articles else 0.0
    label = "Positive" if overall >= 0.3 else ("Negative" if overall <= -0.3 else "Neutral")
    return {"score": overall, "label": label, "articles": articles}


# ---------------------------------------------------------------------------
# Technical indicators
# ---------------------------------------------------------------------------

def _run_technicals(kline_records: list[dict]) -> dict:
    """Run compute_all on kline records. Returns empty-ish dict on failure."""
    import pandas as pd

    empty = {
        "latest_price": 0.0, "sma": {}, "rsi": {"value": None, "period": 14},
        "macd": {"macd": None, "signal": None, "histogram": None},
        "bollinger": {"upper": None, "middle": None, "lower": None, "bandwidth": None},
        "stochastic": {"k": None, "d": None},
        "support_resistance": {"support": [], "resistance": []},
        "signal_score": 0.0, "signal_label": "Neutral", "data_points": 0,
    }
    if not kline_records:
        return empty

    try:
        df = pd.DataFrame(kline_records)
        df = df.rename(columns={"time_key": "date", "trade_vol": "volume", "trade_val": "turnover"})
        return compute_all(df)
    except Exception as exc:
        logger.warning("Technical indicators failed: %s", exc)
        return empty


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(ticker_raw: str, output_dir: str = "outputs") -> str:
    """
    Full pipeline: collect → analyse → generate.

    Returns absolute path to the generated HTML report.
    """
    cfg = load_settings()
    ticker = normalise_ticker(ticker_raw)
    logger.info("Starting pipeline for %s", ticker)

    # ── 1. Market data (MooMoo primary → yfinance fallback) ──────────────
    data_source = "moomoo"
    try:
        moomoo_data = _collect_moomoo(ticker, cfg)
    except PermissionError as exc:
        logger.warning(
            "MooMoo permission error for %s — falling back to yfinance: %s", ticker, exc
        )
        try:
            moomoo_data = _collect_moomoo_yf(ticker, cfg)
            data_source = "yfinance"
        except Exception as yf_exc:
            logger.error("yfinance fallback also failed: %s", yf_exc)
            raise RuntimeError(
                f"Both MooMoo and yfinance failed for {ticker}. "
                f"MooMoo: {exc} | yfinance: {yf_exc}"
            ) from yf_exc
    except Exception as exc:
        logger.error("MooMoo data collection failed: %s", exc)
        raise RuntimeError(
            f"Could not collect market data for {ticker}. "
            f"Ensure OpenD is running on 127.0.0.1:11111 or check network. Error: {exc}"
        ) from exc

    if data_source == "yfinance":
        logger.info("Market data source: yfinance (MooMoo unavailable)")
    else:
        logger.info("Market data source: moomoo")

    snapshot      = moomoo_data["snapshot"]
    kline_records = moomoo_data["kline_records"]

    # ── 2. Technical indicators ───────────────────────────────────────────
    technicals = _run_technicals(kline_records)

    # ── 3. Financials (yfinance) ──────────────────────────────────────────
    try:
        fin_data = _collect_financials(ticker)
    except Exception as exc:
        logger.warning("Financials collection failed: %s — using empty data", exc)
        fin_data = {
            "fundamentals": {"ticker": ticker}, "earnings": {"ticker": ticker, "quarters": []},
            "peers": {"ticker": ticker, "peers": [], "sector_averages": {}},
            "performance": {"ticker": ticker, "benchmark": "^HSI", "performance": []},
        }

    # ── 4. News & sentiment ───────────────────────────────────────────────
    try:
        sentiment = _collect_news(ticker, days=cfg.get("sentiment", {}).get("lookback_days", 7))
    except Exception as exc:
        logger.warning("Sentiment collection failed: %s — skipping", exc)
        sentiment = None

    # ── 5. Generate report ────────────────────────────────────────────────
    path = generate_report(
        ticker=ticker,
        snapshot=snapshot,
        kline_records=kline_records,
        fundamentals=fin_data["fundamentals"],
        earnings=fin_data["earnings"],
        technicals=technicals,
        peers=fin_data["peers"],
        performance=fin_data["performance"],
        sentiment=sentiment,
        output_dir=output_dir,
    )

    # ── 6. Print summary ──────────────────────────────────────────────────
    sig = technicals.get("signal_label", "Neutral")
    score = technicals.get("signal_score", 0.0)
    price = snapshot.get("last_price") or technicals.get("latest_price") or "N/A"
    chg   = snapshot.get("change_rate") or 0.0

    sep = "-" * 48
    print(f"\n{sep}")
    print(f"  {ticker} - {snapshot.get('name', '')}")
    print(f"{sep}")
    print(f"  Report : {path}")
    print(f"  Price  : {price}  ({'+' if chg >= 0 else ''}{chg:.2f}%)")
    print(f"  Signal : {sig}  (score {score:+.2f})")
    rsi_v = technicals.get("rsi", {}).get("value")
    if rsi_v:
        print(f"  RSI    : {rsi_v:.1f}")
    print(f"{sep}\n")

    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="moomoo-dashboard — generate equity research report",
    )
    parser.add_argument("ticker", help="Ticker symbol (e.g. HK.00700, US.AAPL, NVDA, 00700)")
    parser.add_argument("--output-dir", default="outputs", help="Output directory (default: outputs)")
    args = parser.parse_args()

    try:
        path = run(args.ticker, output_dir=args.output_dir)
        sys.exit(0)
    except RuntimeError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
