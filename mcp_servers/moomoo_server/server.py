"""
MCP Server: moomoo_server

Exposes MooMoo OpenD market data as MCP tools for use by Claude Code skills.
Connects to a locally running OpenD gateway (default 127.0.0.1:11111).

MooMoo is the primary data source.  When MooMoo returns a permission error
("No right", "no permission") or a connection error, the server automatically
falls back to yfinance.  The returned JSON always includes a
``"source": "moomoo" | "yfinance"`` field so callers can see which backend was used.

Tools exposed:
  - get_snapshot        : real-time snapshot for a single ticker
  - get_kline           : historical K-line / candlestick data
  - get_plate_list      : list available sector plates for a market
  - get_plate_stocks    : list stocks inside a plate
  - get_plate_for_stock : find which plates a ticker belongs to
  - get_multi_snapshot  : snapshots for multiple tickers (peer comparison)
"""

import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import moomoo as ft
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Ensure src/ is importable when running as a standalone MCP server
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.sector_mapper import _US_SECTOR_PEERS, _HK_SECTOR_PEERS, moomoo_to_yfinance  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("moomoo_server")

# ---------------------------------------------------------------------------
# Config from environment (set via .claude.json)
# ---------------------------------------------------------------------------
MOOMOO_HOST = os.environ.get("MOOMOO_HOST", "127.0.0.1")
MOOMOO_PORT = int(os.environ.get("MOOMOO_PORT", "11111"))

# Error substrings that trigger a yfinance fallback
_FALLBACK_TRIGGERS = (
    "no right",
    "no permission",
    "not connected",
    "permission",
    "quota",
    "subscription",
)

# ---------------------------------------------------------------------------
# MCP app
# ---------------------------------------------------------------------------
mcp = FastMCP("moomoo_server")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quote_ctx() -> ft.OpenQuoteContext:
    """Open a new quote context. Caller is responsible for closing it."""
    return ft.OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)


def _normalize_ticker(ticker: str, default_market: str = "HK") -> str:
    """
    Ensure the ticker has a market prefix (e.g. HK.00700, US.AAPL).
    If no prefix is present, prepend `default_market`.
    """
    ticker = ticker.strip().upper()
    if "." in ticker:
        return ticker
    return f"{default_market}.{ticker}"


def _ret_to_error(ret: int, data: Any) -> str:
    """Return a JSON-encoded error message for a failed moomoo call."""
    return json.dumps({"error": str(data)})


def _df_to_records(df) -> list[dict]:
    """Convert a pandas DataFrame to a list of dicts (JSON-serialisable)."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _is_permission_error(msg: str) -> bool:
    """Return True if *msg* indicates a MooMoo access/permission error."""
    lower = str(msg).lower()
    return any(trigger in lower for trigger in _FALLBACK_TRIGGERS)


# ---------------------------------------------------------------------------
# yfinance fallback helpers
# ---------------------------------------------------------------------------

def _yf_snapshot(moomoo_ticker: str) -> dict:
    """Build a snapshot dict from yfinance for a single ticker."""
    import yfinance as yf

    yf_code = moomoo_to_yfinance(moomoo_ticker)
    info = yf.Ticker(yf_code).info

    # Current price fallback chain
    price = (info.get("currentPrice")
             or info.get("regularMarketPrice")
             or info.get("ask")
             or info.get("bid"))
    prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
    change_val  = (price - prev_close) if (price and prev_close) else None
    change_rate = (change_val / prev_close * 100) if (change_val and prev_close) else None

    return {
        "ticker":         moomoo_ticker,
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
        "lot_size":       None,
        "stock_type":     None,
        "listing_date":   None,
        "source":         "yfinance",
    }


def _yf_kline(moomoo_ticker: str, days: int = 180) -> dict:
    """Build a kline dict from yfinance for a single ticker."""
    import yfinance as yf

    yf_code   = moomoo_to_yfinance(moomoo_ticker)
    end_date  = date.today()
    start_date = end_date - timedelta(days=days)

    hist = yf.download(
        yf_code,
        start=str(start_date),
        end=str(end_date),
        auto_adjust=True,
        progress=False,
    )

    records = []
    if not hist.empty:
        # yf.download may return MultiIndex columns
        if hasattr(hist.columns, "levels"):
            # collapse single-ticker MultiIndex
            hist.columns = hist.columns.get_level_values(0)
        for ts, row in hist.iterrows():
            records.append({
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

    return {
        "ticker":     moomoo_ticker,
        "kline_type": "K_DAY",
        "records":    records,
        "source":     "yfinance",
    }


# ---------------------------------------------------------------------------
# Tool: get_snapshot
# ---------------------------------------------------------------------------

@mcp.tool()
def get_snapshot(ticker: str) -> str:
    """
    Get a real-time market snapshot for a single ticker.

    Returns price, volume, turnover, market cap, P/E, P/B, 52-week high/low,
    dividend yield, and change percentage.  A ``"source"`` field indicates
    whether data came from MooMoo ("moomoo") or the yfinance fallback
    ("yfinance").

    MooMoo is tried first; if it returns a permission/connection error the
    server automatically retries with yfinance.

    Args:
        ticker: Ticker symbol with optional market prefix (e.g. "HK.00700",
                "US.AAPL", "00700", "AAPL").  Defaults to HK market if no
                prefix is supplied.
    """
    code = _normalize_ticker(ticker)
    logger.info("get_snapshot: %s", code)

    moomoo_error: str = ""
    is_connection_exc = False

    # ── Try MooMoo first ───────────────────────────────────────────────────
    try:
        ctx = _quote_ctx()
        ret, data = ctx.get_market_snapshot([code])
        ctx.close()

        if ret != ft.RET_OK:
            moomoo_error = str(data)
        else:
            records = _df_to_records(data)
            if not records:
                moomoo_error = f"No snapshot data returned for {code}"
            else:
                row = records[0]
                result = {
                    "ticker":         code,
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
                    "lot_size":       row.get("lot_size"),
                    "stock_type":     row.get("stock_type"),
                    "listing_date":   row.get("listing_date"),
                    "source":         "moomoo",
                }
                return json.dumps(result, default=str)

    except Exception as exc:
        moomoo_error = f"OpenD connection error: {exc}"
        is_connection_exc = True

    # ── Decide whether to fall back ────────────────────────────────────────
    # Fall back on: any connection exception OR permission-related API error.
    # Other API errors (symbol not found, no data, etc.) return the error.
    if not (is_connection_exc or _is_permission_error(moomoo_error)):
        return json.dumps({"error": moomoo_error})

    logger.warning("MooMoo unavailable for %s, falling back to yfinance (%s)", code, moomoo_error)

    try:
        result = _yf_snapshot(code)
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": f"MooMoo: {moomoo_error} | yfinance: {exc}"})


# ---------------------------------------------------------------------------
# Tool: get_kline
# ---------------------------------------------------------------------------

@mcp.tool()
def get_kline(
    ticker: str,
    days: int = 180,
    kline_type: str = "K_DAY",
) -> str:
    """
    Get historical K-line (candlestick) data for a ticker.

    MooMoo is the primary source; automatically falls back to yfinance when
    MooMoo returns a permission or connection error.  The response includes a
    ``"source"`` field ("moomoo" or "yfinance").

    Args:
        ticker:     Ticker symbol (e.g. "HK.00700", "US.AAPL"). Defaults to
                    HK market if no prefix is supplied.
        days:       Number of calendar days to look back (default 180).
        kline_type: MooMoo K-line type string. Common values:
                    K_1M, K_5M, K_15M, K_30M, K_60M, K_DAY, K_WEEK, K_MON.
                    Default is K_DAY.  Ignored when yfinance fallback is used
                    (always returns daily bars).

    Returns JSON with keys: ticker, kline_type, records (list of OHLCV), source.
    """
    code = _normalize_ticker(ticker)
    end_date   = date.today()
    start_date = end_date - timedelta(days=days)
    logger.info("get_kline: %s  type=%s  %s → %s", code, kline_type, start_date, end_date)

    ktype_map: dict[str, ft.KLType] = {
        "K_1M": ft.KLType.K_1M, "K_5M": ft.KLType.K_5M,
        "K_15M": ft.KLType.K_15M, "K_30M": ft.KLType.K_30M,
        "K_60M": ft.KLType.K_60M, "K_DAY": ft.KLType.K_DAY,
        "K_WEEK": ft.KLType.K_WEEK, "K_MON": ft.KLType.K_MON,
    }
    ktype = ktype_map.get(kline_type.upper(), ft.KLType.K_DAY)
    fields = [
        ft.KL_FIELD.DATE_TIME, ft.KL_FIELD.OPEN,  ft.KL_FIELD.CLOSE,
        ft.KL_FIELD.HIGH,      ft.KL_FIELD.LOW,   ft.KL_FIELD.TRADE_VOL,
        ft.KL_FIELD.TRADE_VAL, ft.KL_FIELD.CHANGE_RATE,
        ft.KL_FIELD.LAST_CLOSE, ft.KL_FIELD.PE_RATIO,
    ]

    moomoo_error: str = ""
    is_connection_exc = False

    # ── Try MooMoo first ───────────────────────────────────────────────────
    try:
        ctx = _quote_ctx()
        ret, data, _ = ctx.get_history_kline(
            code,
            start=str(start_date), end=str(end_date),
            ktype=ktype, autype=ft.AuType.QFQ,
            fields=fields, max_count=1000,
        )
        ctx.close()

        if ret != ft.RET_OK:
            moomoo_error = str(data)
        else:
            records = _df_to_records(data)
            return json.dumps({
                "ticker": code, "kline_type": kline_type,
                "records": records, "source": "moomoo",
            })

    except Exception as exc:
        moomoo_error = f"OpenD connection error: {exc}"
        is_connection_exc = True

    # ── Fallback ───────────────────────────────────────────────────────────
    if not (is_connection_exc or _is_permission_error(moomoo_error)):
        return json.dumps({"error": moomoo_error})

    logger.warning("MooMoo unavailable for %s, falling back to yfinance (%s)", code, moomoo_error)

    try:
        return json.dumps(_yf_kline(code, days=days))
    except Exception as exc:
        return json.dumps({"error": f"MooMoo: {moomoo_error} | yfinance: {exc}"})


# ---------------------------------------------------------------------------
# Tool: get_plate_list   (MooMoo-only — no yfinance equivalent)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_plate_list(market: str = "HK") -> str:
    """
    List available sector/industry plates for a given market.

    This tool is MooMoo-specific.  There is no yfinance equivalent, so if
    MooMoo is unavailable the tool returns an error with
    ``"source": "moomoo_only"``.

    Args:
        market: Market code — "HK", "US", or "CN" (default "HK").

    Returns a JSON list of plate records with fields:
        plate_id, plate_name, plate_type.
    """
    market = market.upper()
    logger.info("get_plate_list: market=%s", market)

    market_map = {
        "HK": ft.Market.HK,
        "US": ft.Market.US,
        "CN": ft.Market.SH,
    }
    mkt = market_map.get(market, ft.Market.HK)

    try:
        ctx = _quote_ctx()
        ret, data = ctx.get_plate_list(mkt, ft.Plate.INDUSTRY)
        ctx.close()
    except Exception as exc:
        logger.exception("OpenD connection error")
        return json.dumps({
            "error": f"OpenD connection error: {exc}",
            "source": "moomoo_only",
        })

    if ret != ft.RET_OK:
        return json.dumps({"error": str(data), "source": "moomoo_only"})

    records = _df_to_records(data)
    return json.dumps({"market": market, "plates": records, "source": "moomoo"})


# ---------------------------------------------------------------------------
# Tool: get_plate_stocks   (MooMoo-only — no yfinance equivalent)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_plate_stocks(plate_code: str) -> str:
    """
    List all stocks inside a specific sector plate.

    This tool is MooMoo-specific.  There is no yfinance equivalent, so if
    MooMoo is unavailable the tool returns an error with
    ``"source": "moomoo_only"``.

    Args:
        plate_code: MooMoo plate identifier (e.g. "HK.BK1001").

    Returns a JSON list of stock records with fields:
        code, name, lot_size, stock_type, stock_child_type, main_contract,
        last_trade_time.
    """
    plate_code = plate_code.strip().upper()
    logger.info("get_plate_stocks: %s", plate_code)

    try:
        ctx = _quote_ctx()
        ret, data = ctx.get_plate_stock(plate_code)
        ctx.close()
    except Exception as exc:
        logger.exception("OpenD connection error")
        return json.dumps({
            "error": f"OpenD connection error: {exc}",
            "source": "moomoo_only",
        })

    if ret != ft.RET_OK:
        return json.dumps({"error": str(data), "source": "moomoo_only"})

    records = _df_to_records(data)
    return json.dumps({"plate_code": plate_code, "stocks": records, "source": "moomoo"})


# ---------------------------------------------------------------------------
# Tool: get_plate_for_stock
# ---------------------------------------------------------------------------

@mcp.tool()
def get_plate_for_stock(ticker: str) -> str:
    """
    Find which sector plates a stock belongs to.

    MooMoo is tried first.  If MooMoo is unavailable, falls back to
    yfinance ``info["sector"]`` and returns the curated list of sector peers
    from sector_mapper.py.  The response includes ``"source"``.

    Args:
        ticker: Ticker symbol (e.g. "HK.00700", "US.AAPL").

    Returns a JSON object with:
        ticker, plates (list), source.
    """
    code = _normalize_ticker(ticker)
    logger.info("get_plate_for_stock: %s", code)

    moomoo_error: str = ""
    is_connection_exc = False

    # ── Try MooMoo first ───────────────────────────────────────────────────
    try:
        ctx = _quote_ctx()
        ret2, data2 = ctx.get_owner_plate([code])
        ctx.close()

        if ret2 != ft.RET_OK:
            moomoo_error = str(data2)
        else:
            records = _df_to_records(data2)
            return json.dumps({"ticker": code, "plates": records, "source": "moomoo"})

    except Exception as exc:
        moomoo_error = f"OpenD connection error: {exc}"
        is_connection_exc = True

    # ── Fallback: yfinance sector info ─────────────────────────────────────
    if not (is_connection_exc or _is_permission_error(moomoo_error)):
        return json.dumps({"error": moomoo_error})

    logger.warning("MooMoo unavailable for %s, falling back to yfinance (%s)", code, moomoo_error)

    try:
        import yfinance as yf

        yf_code = moomoo_to_yfinance(code)
        info    = yf.Ticker(yf_code).info
        sector  = info.get("sector") or "Unknown"
        industry = info.get("industry") or "Unknown"

        # Look up curated peer list
        peer_map = _HK_SECTOR_PEERS if code.startswith("HK.") else _US_SECTOR_PEERS
        peers    = peer_map.get(sector, [])

        return json.dumps({
            "ticker":   code,
            "sector":   sector,
            "industry": industry,
            "plates":   [{"plate_name": sector, "plate_type": "INDUSTRY"}],
            "suggested_peers": peers[:10],
            "source":   "yfinance",
        })
    except Exception as exc:
        return json.dumps({"error": f"MooMoo: {moomoo_error} | yfinance: {exc}"})


# ---------------------------------------------------------------------------
# Tool: get_multi_snapshot
# ---------------------------------------------------------------------------

@mcp.tool()
def get_multi_snapshot(tickers: list[str]) -> str:
    """
    Get market snapshots for multiple tickers in a single call.

    MooMoo is tried first; automatically falls back to yfinance (per-ticker)
    when MooMoo returns a permission or connection error.  The response
    includes a top-level ``"source"`` field and each record also carries
    ``"source"``.

    Args:
        tickers: List of ticker symbols (e.g. ["HK.00700", "HK.00005"]).
                 Defaults to HK market when no prefix is supplied.

    Returns a JSON object with keys: snapshots (list), source.
    """
    if not tickers:
        return json.dumps({"error": "tickers list is empty"})

    codes = [_normalize_ticker(t) for t in tickers]
    logger.info("get_multi_snapshot: %s", codes)

    moomoo_error: str = ""
    is_connection_exc = False

    # ── Try MooMoo first ───────────────────────────────────────────────────
    try:
        ctx = _quote_ctx()
        ret, data = ctx.get_market_snapshot(codes)
        ctx.close()

        if ret != ft.RET_OK:
            moomoo_error = str(data)
        else:
            records = _df_to_records(data)
            result = []
            for row in records:
                result.append({
                    "ticker":         row.get("code", ""),
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
                })
            return json.dumps({"snapshots": result, "source": "moomoo"}, default=str)

    except Exception as exc:
        moomoo_error = f"OpenD connection error: {exc}"
        is_connection_exc = True

    # ── Fallback: per-ticker yfinance ──────────────────────────────────────
    if not (is_connection_exc or _is_permission_error(moomoo_error)):
        return json.dumps({"error": moomoo_error})

    logger.warning(
        "MooMoo unavailable for %s, falling back to yfinance (%s)", codes, moomoo_error
    )

    result = []
    errors = []
    for code in codes:
        try:
            snap = _yf_snapshot(code)
            result.append(snap)
        except Exception as exc:
            errors.append({"ticker": code, "error": str(exc)})

    out: dict = {"snapshots": result, "source": "yfinance"}
    if errors:
        out["errors"] = errors
    return json.dumps(out, default=str)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting moomoo_server MCP (OpenD at %s:%d)", MOOMOO_HOST, MOOMOO_PORT)
    mcp.run()
