"""
MCP Server: financials_server

Exposes fundamental financial data as MCP tools using yfinance.
Works for both HK and US stocks; no OpenD connection required.

Tools exposed:
  - get_fundamentals     : P/E, P/B, ROE, EPS, market cap, beta, sector, etc.
  - get_earnings         : Last 4 quarters of revenue, net income, EPS
  - get_peer_comparison  : Side-by-side fundamental comparison vs sector peers
  - get_performance      : Cumulative return vs a benchmark over multiple periods
"""

import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yfinance as yf
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Make src/ importable when running as a standalone MCP server
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.sector_mapper import get_sector_peers, moomoo_to_yfinance  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("financials_server")

# ---------------------------------------------------------------------------
# MCP app
# ---------------------------------------------------------------------------
mcp = FastMCP("financials_server")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_yf(ticker: str) -> str:
    """
    Accept either MooMoo format (HK.00700, US.AAPL) or plain yfinance format
    (0700.HK, AAPL) and always return yfinance format.
    """
    ticker = ticker.strip()
    if "." in ticker and ticker.split(".")[0].upper() in ("HK", "US", "CN"):
        return moomoo_to_yfinance(ticker)
    return ticker


def _safe(val: Any) -> Any:
    """Convert NaN/inf to None for JSON serialisation."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    return val


def _round(val: Any, ndigits: int = 4) -> Any:
    v = _safe(val)
    if v is None:
        return None
    try:
        return round(float(v), ndigits)
    except (TypeError, ValueError):
        return v


def _default_benchmark(yf_ticker: str) -> str:
    """Return the most relevant benchmark index for a ticker."""
    return "^HSI" if yf_ticker.endswith(".HK") else "^GSPC"


# ---------------------------------------------------------------------------
# Tool: get_fundamentals
# ---------------------------------------------------------------------------

@mcp.tool()
def get_fundamentals(ticker: str) -> str:
    """
    Get fundamental data for a stock.

    Returns P/E, P/B, ROE, EPS, market cap, dividend yield, 52-week
    high/low, beta, sector, and industry.

    Args:
        ticker: Ticker in MooMoo format (e.g. "HK.00700", "US.AAPL") or
                yfinance format (e.g. "0700.HK", "AAPL").
    """
    yf_code = _to_yf(ticker)
    logger.info("get_fundamentals: %s (yf: %s)", ticker, yf_code)

    try:
        info = yf.Ticker(yf_code).info
    except Exception as exc:
        logger.exception("yfinance error")
        return json.dumps({"error": f"yfinance error: {exc}"})

    if not info or info.get("trailingPE") is None and info.get("currentPrice") is None:
        return json.dumps({"error": f"No data returned for {yf_code}"})

    result = {
        "ticker": ticker,
        "yf_ticker": yf_code,
        "name": _safe(info.get("longName") or info.get("shortName")),
        "sector": _safe(info.get("sector")),
        "industry": _safe(info.get("industry")),
        "market_cap": _safe(info.get("marketCap")),
        "currency": _safe(info.get("currency")),
        "current_price": _round(info.get("currentPrice") or info.get("regularMarketPrice"), 3),
        "pe_ratio": _round(info.get("trailingPE")),
        "forward_pe": _round(info.get("forwardPE")),
        "pb_ratio": _round(info.get("priceToBook")),
        "ps_ratio": _round(info.get("priceToSalesTrailing12Months")),
        "roe": _round(info.get("returnOnEquity"), 4),          # decimal (e.g. 0.28 = 28%)
        "roa": _round(info.get("returnOnAssets"), 4),
        "eps_ttm": _round(info.get("trailingEps"), 3),
        "eps_forward": _round(info.get("forwardEps"), 3),
        "revenue_ttm": _safe(info.get("totalRevenue")),
        "net_income_ttm": _safe(info.get("netIncomeToCommon")),
        "profit_margin": _round(info.get("profitMargins"), 4),
        "dividend_yield": _round(info.get("dividendYield"), 4),  # decimal (e.g. 0.02 = 2%)
        "dividend_rate": _round(info.get("dividendRate"), 3),
        "beta": _round(info.get("beta"), 3),
        "52w_high": _round(info.get("fiftyTwoWeekHigh"), 3),
        "52w_low": _round(info.get("fiftyTwoWeekLow"), 3),
        "shares_outstanding": _safe(info.get("sharesOutstanding")),
        "float_shares": _safe(info.get("floatShares")),
        "book_value": _round(info.get("bookValue"), 3),
        "debt_to_equity": _round(info.get("debtToEquity"), 2),
        "current_ratio": _round(info.get("currentRatio"), 2),
        "quick_ratio": _round(info.get("quickRatio"), 2),
        "gross_margin": _round(info.get("grossMargins"), 4),
        "operating_margin": _round(info.get("operatingMargins"), 4),
        "ebitda": _safe(info.get("ebitda")),
        "enterprise_value": _safe(info.get("enterpriseValue")),
        "ev_to_ebitda": _round(info.get("enterpriseToEbitda")),
        "ev_to_revenue": _round(info.get("enterpriseToRevenue")),
        "short_ratio": _round(info.get("shortRatio"), 2),
        "analyst_target": _round(info.get("targetMeanPrice"), 3),
        "recommendation": _safe(info.get("recommendationKey")),
    }
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: get_earnings
# ---------------------------------------------------------------------------

@mcp.tool()
def get_earnings(ticker: str) -> str:
    """
    Get quarterly earnings data for the last 4 reported quarters.

    Returns revenue, net income, EPS actual, and EPS estimate for each quarter.

    Args:
        ticker: Ticker in MooMoo format (e.g. "HK.00700", "US.AAPL") or
                yfinance format (e.g. "0700.HK", "AAPL").
    """
    yf_code = _to_yf(ticker)
    logger.info("get_earnings: %s (yf: %s)", ticker, yf_code)

    try:
        t = yf.Ticker(yf_code)
        quarterly_financials = t.quarterly_financials
        quarterly_earnings = t.quarterly_earnings
    except Exception as exc:
        logger.exception("yfinance error")
        return json.dumps({"error": f"yfinance error: {exc}"})

    quarters: list[dict] = []

    # quarterly_financials columns are Timestamps (most recent first)
    if quarterly_financials is not None and not quarterly_financials.empty:
        fin = quarterly_financials
        for col in list(fin.columns)[:4]:  # last 4 quarters
            period_str = str(col.date()) if hasattr(col, "date") else str(col)
            row: dict[str, Any] = {"period": period_str}

            def _get_row(label: str) -> Optional[float]:
                for idx in fin.index:
                    if label.lower() in str(idx).lower():
                        val = fin.loc[idx, col]
                        return _safe(val)
                return None

            row["revenue"] = _get_row("total revenue")
            row["gross_profit"] = _get_row("gross profit")
            row["net_income"] = _get_row("net income")
            row["ebitda"] = _get_row("ebitda")

            # Merge EPS data from quarterly_earnings if available
            if quarterly_earnings is not None and not quarterly_earnings.empty:
                if period_str in quarterly_earnings.index.astype(str):
                    qe_row = quarterly_earnings.loc[period_str]
                    row["eps_actual"] = _round(qe_row.get("Earnings"), 3) if hasattr(qe_row, "get") else None
                    row["eps_estimate"] = _round(qe_row.get("Estimate"), 3) if hasattr(qe_row, "get") else None

            quarters.append(row)

    if not quarters:
        return json.dumps({"error": f"No earnings data available for {yf_code}"})

    return json.dumps({"ticker": ticker, "yf_ticker": yf_code, "quarters": quarters}, default=str)


# ---------------------------------------------------------------------------
# Tool: get_peer_comparison
# ---------------------------------------------------------------------------

@mcp.tool()
def get_peer_comparison(ticker: str, max_peers: int = 8) -> str:
    """
    Compare a stock against its sector peers on key fundamental metrics.

    Fetches fundamentals for the target stock and up to max_peers peers,
    then returns a comparison table with P/E, P/B, market cap, ROE,
    dividend yield, EPS, and YTD return.

    Args:
        ticker:    Ticker in MooMoo or yfinance format.
        max_peers: Maximum number of peer tickers to include (default 8).
    """
    yf_code = _to_yf(ticker)
    logger.info("get_peer_comparison: %s (yf: %s)", ticker, yf_code)

    # Find peers
    peers = get_sector_peers(yf_code, max_peers=max_peers, include_self=False)
    all_tickers = [yf_code] + peers
    logger.info("Fetching fundamentals for %d tickers: %s", len(all_tickers), all_tickers)

    year_start = date(date.today().year, 1, 1)
    rows: list[dict] = []

    for code in all_tickers:
        try:
            t = yf.Ticker(code)
            info = t.info

            # YTD return
            ytd_return: Optional[float] = None
            try:
                hist = t.history(start=str(year_start), auto_adjust=True)
                if not hist.empty and len(hist) >= 2:
                    ytd_return = round(
                        (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100, 2
                    )
            except Exception:
                pass

            rows.append({
                "ticker": code,
                "is_target": code == yf_code,
                "name": _safe(info.get("longName") or info.get("shortName")),
                "sector": _safe(info.get("sector")),
                "market_cap": _safe(info.get("marketCap")),
                "current_price": _round(info.get("currentPrice") or info.get("regularMarketPrice"), 3),
                "pe_ratio": _round(info.get("trailingPE")),
                "pb_ratio": _round(info.get("priceToBook")),
                "ps_ratio": _round(info.get("priceToSalesTrailing12Months")),
                "roe": _round(info.get("returnOnEquity"), 4),
                "eps_ttm": _round(info.get("trailingEps"), 3),
                "dividend_yield": _round(info.get("dividendYield"), 4),
                "beta": _round(info.get("beta"), 3),
                "ytd_return_pct": ytd_return,
                "analyst_target": _round(info.get("targetMeanPrice"), 3),
                "recommendation": _safe(info.get("recommendationKey")),
            })
        except Exception as exc:
            logger.warning("Failed to fetch data for %s: %s", code, exc)

    if not rows:
        return json.dumps({"error": f"Could not fetch peer data for {yf_code}"})

    # Compute sector averages for numeric columns
    numeric_cols = ["pe_ratio", "pb_ratio", "roe", "eps_ttm", "dividend_yield", "ytd_return_pct"]
    averages: dict[str, Optional[float]] = {}
    for col in numeric_cols:
        vals = [r[col] for r in rows if r[col] is not None]
        averages[col] = round(sum(vals) / len(vals), 4) if vals else None

    return json.dumps(
        {
            "ticker": ticker,
            "yf_ticker": yf_code,
            "peers": rows,
            "sector_averages": averages,
        },
        default=str,
    )


# ---------------------------------------------------------------------------
# Tool: get_performance
# ---------------------------------------------------------------------------

@mcp.tool()
def get_performance(
    ticker: str,
    benchmark: Optional[str] = None,
) -> str:
    """
    Calculate cumulative return for a stock vs a benchmark over 1M/3M/6M/1Y.

    Args:
        ticker:    Ticker in MooMoo or yfinance format.
        benchmark: yfinance benchmark ticker (e.g. "^HSI", "^GSPC", "^IXIC").
                   Defaults to ^HSI for HK stocks, ^GSPC for US stocks.
    """
    yf_code = _to_yf(ticker)
    bench = benchmark or _default_benchmark(yf_code)
    logger.info("get_performance: %s vs %s", yf_code, bench)

    periods = [
        ("1M",  30),
        ("3M",  90),
        ("6M", 180),
        ("1Y", 365),
    ]

    today = date.today()
    # Fetch 1 year + buffer of daily data for both tickers in one shot
    start = str(today - timedelta(days=380))

    try:
        raw = yf.download(
            [yf_code, bench],
            start=start,
            auto_adjust=True,
            progress=False,
        )
    except Exception as exc:
        logger.exception("yfinance download error")
        return json.dumps({"error": f"yfinance download error: {exc}"})

    # yf.download returns MultiIndex columns when multiple tickers
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]].rename(columns={"Close": yf_code})

    if yf_code not in close.columns or close[yf_code].dropna().empty:
        return json.dumps({"error": f"No price data for {yf_code}"})

    results: list[dict] = []
    for label, days in periods:
        cutoff = today - timedelta(days=days)

        def _cum_return(col: str) -> Optional[float]:
            if col not in close.columns:
                return None
            s = close[col].dropna()
            s = s[s.index.date >= cutoff]
            if len(s) < 2:
                return None
            return round((float(s.iloc[-1]) / float(s.iloc[0]) - 1) * 100, 2)

        results.append({
            "period": label,
            "days": days,
            "ticker_return_pct": _cum_return(yf_code),
            "benchmark_return_pct": _cum_return(bench),
        })

    # Add alpha (ticker return minus benchmark return) for each period
    for r in results:
        t_ret = r["ticker_return_pct"]
        b_ret = r["benchmark_return_pct"]
        r["alpha_pct"] = round(t_ret - b_ret, 2) if (t_ret is not None and b_ret is not None) else None

    return json.dumps(
        {
            "ticker": ticker,
            "yf_ticker": yf_code,
            "benchmark": bench,
            "performance": results,
        },
        default=str,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting financials_server MCP")
    mcp.run()
