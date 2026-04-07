"""
MCP Server: moomoo_server

Exposes MooMoo OpenD market data as MCP tools for use by Claude Code skills.
Connects to a locally running OpenD gateway (default 127.0.0.1:11111).

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
from datetime import date, timedelta
from typing import Any

import moomoo as ft
from mcp.server.fastmcp import FastMCP

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


# ---------------------------------------------------------------------------
# Tool: get_snapshot
# ---------------------------------------------------------------------------

@mcp.tool()
def get_snapshot(ticker: str) -> str:
    """
    Get a real-time market snapshot for a single ticker.

    Returns price, volume, turnover, market cap, P/E, P/B, 52-week high/low,
    dividend yield, and change percentage.

    Args:
        ticker: Ticker symbol with optional market prefix (e.g. "HK.00700",
                "US.AAPL", "00700", "AAPL").  Defaults to HK market if no
                prefix is supplied.
    """
    code = _normalize_ticker(ticker)
    logger.info("get_snapshot: %s", code)

    try:
        ctx = _quote_ctx()
        ret, data = ctx.get_market_snapshot([code])
        ctx.close()
    except Exception as exc:
        logger.exception("OpenD connection error")
        return json.dumps({"error": f"OpenD connection error: {exc}"})

    if ret != ft.RET_OK:
        return _ret_to_error(ret, data)

    records = _df_to_records(data)
    if not records:
        return json.dumps({"error": f"No snapshot data returned for {code}"})

    row = records[0]
    result = {
        "ticker": code,
        "name": row.get("name", ""),
        "last_price": row.get("last_price"),
        "change_val": row.get("change_val"),
        "change_rate": row.get("change_rate"),         # %
        "volume": row.get("volume"),
        "turnover": row.get("turnover"),
        "market_cap": row.get("market_cap"),
        "pe_ratio": row.get("pe_ratio"),
        "pb_ratio": row.get("pb_ratio"),
        "52w_high": row.get("high_price_52weeks"),
        "52w_low": row.get("low_price_52weeks"),
        "dividend_yield": row.get("dividend_yield"),
        "lot_size": row.get("lot_size"),
        "stock_type": row.get("stock_type"),
        "listing_date": row.get("listing_date"),
    }
    return json.dumps(result, default=str)


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

    Args:
        ticker:     Ticker symbol (e.g. "HK.00700", "US.AAPL"). Defaults to
                    HK market if no prefix is supplied.
        days:       Number of calendar days to look back (default 180).
        kline_type: MooMoo K-line type string. Common values:
                    K_1M, K_5M, K_15M, K_30M, K_60M, K_DAY, K_WEEK, K_MON.
                    Default is K_DAY.

    Returns JSON list of OHLCV records with fields:
        time_key, open, close, high, low, volume, turnover, change_rate,
        last_close, pe_ratio, pb_ratio.
    """
    code = _normalize_ticker(ticker)
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    logger.info("get_kline: %s  type=%s  %s → %s", code, kline_type, start_date, end_date)

    # Map string to moomoo KLType enum
    ktype_map: dict[str, ft.KLType] = {
        "K_1M": ft.KLType.K_1M,
        "K_5M": ft.KLType.K_5M,
        "K_15M": ft.KLType.K_15M,
        "K_30M": ft.KLType.K_30M,
        "K_60M": ft.KLType.K_60M,
        "K_DAY": ft.KLType.K_DAY,
        "K_WEEK": ft.KLType.K_WEEK,
        "K_MON": ft.KLType.K_MON,
    }
    ktype = ktype_map.get(kline_type.upper(), ft.KLType.K_DAY)
    fields = [
        ft.KL_FIELD.DATE_TIME,
        ft.KL_FIELD.OPEN,
        ft.KL_FIELD.CLOSE,
        ft.KL_FIELD.HIGH,
        ft.KL_FIELD.LOW,
        ft.KL_FIELD.TRADE_VOL,      # volume
        ft.KL_FIELD.TRADE_VAL,      # turnover
        ft.KL_FIELD.CHANGE_RATE,
        ft.KL_FIELD.LAST_CLOSE,
        ft.KL_FIELD.PE_RATIO,
    ]

    try:
        ctx = _quote_ctx()
        ret, data, page_req_key = ctx.get_history_kline(
            code,
            start=str(start_date),
            end=str(end_date),
            ktype=ktype,
            autype=ft.AuType.QFQ,          # forward-adjusted
            fields=fields,
            max_count=1000,
        )
        ctx.close()
    except Exception as exc:
        logger.exception("OpenD connection error")
        return json.dumps({"error": f"OpenD connection error: {exc}"})

    if ret != ft.RET_OK:
        return _ret_to_error(ret, data)

    records = _df_to_records(data)
    return json.dumps({"ticker": code, "kline_type": kline_type, "records": records})


# ---------------------------------------------------------------------------
# Tool: get_plate_list
# ---------------------------------------------------------------------------

@mcp.tool()
def get_plate_list(market: str = "HK") -> str:
    """
    List available sector/industry plates for a given market.

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
        "CN": ft.Market.SH,  # mainland uses SH/SZ; SH is a reasonable default
    }
    mkt = market_map.get(market, ft.Market.HK)

    try:
        ctx = _quote_ctx()
        ret, data = ctx.get_plate_list(mkt, ft.Plate.INDUSTRY)
        ctx.close()
    except Exception as exc:
        logger.exception("OpenD connection error")
        return json.dumps({"error": f"OpenD connection error: {exc}"})

    if ret != ft.RET_OK:
        return _ret_to_error(ret, data)

    records = _df_to_records(data)
    return json.dumps({"market": market, "plates": records})


# ---------------------------------------------------------------------------
# Tool: get_plate_stocks
# ---------------------------------------------------------------------------

@mcp.tool()
def get_plate_stocks(plate_code: str) -> str:
    """
    List all stocks inside a specific sector plate.

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
        return json.dumps({"error": f"OpenD connection error: {exc}"})

    if ret != ft.RET_OK:
        return _ret_to_error(ret, data)

    records = _df_to_records(data)
    return json.dumps({"plate_code": plate_code, "stocks": records})


# ---------------------------------------------------------------------------
# Tool: get_plate_for_stock
# ---------------------------------------------------------------------------

@mcp.tool()
def get_plate_for_stock(ticker: str) -> str:
    """
    Find which sector plates a stock belongs to.

    Args:
        ticker: Ticker symbol (e.g. "HK.00700", "US.AAPL").

    Returns a JSON list of plate records containing:
        plate_id, plate_name, plate_type.
    """
    code = _normalize_ticker(ticker)
    logger.info("get_plate_for_stock: %s", code)

    try:
        ctx = _quote_ctx()
        ret, data = ctx.get_stock_basicinfo(
            ft.Market.HK if code.startswith("HK.") else ft.Market.US,
            ft.SecurityType.STOCK,
            [code],
        )
        # get_owner_plate is the correct API for "which plate does this stock belong to"
        ret2, data2 = ctx.get_owner_plate([code])
        ctx.close()
    except Exception as exc:
        logger.exception("OpenD connection error")
        return json.dumps({"error": f"OpenD connection error: {exc}"})

    if ret2 != ft.RET_OK:
        return _ret_to_error(ret2, data2)

    records = _df_to_records(data2)
    return json.dumps({"ticker": code, "plates": records})


# ---------------------------------------------------------------------------
# Tool: get_multi_snapshot
# ---------------------------------------------------------------------------

@mcp.tool()
def get_multi_snapshot(tickers: list[str]) -> str:
    """
    Get market snapshots for multiple tickers in a single call.

    Useful for peer / sector comparisons.  All tickers are fetched in one
    round-trip to OpenD.

    Args:
        tickers: List of ticker symbols (e.g. ["HK.00700", "HK.00005"]).
                 Defaults to HK market when no prefix is supplied.

    Returns a JSON list where each element is a snapshot record (same fields
    as get_snapshot).
    """
    if not tickers:
        return json.dumps({"error": "tickers list is empty"})

    codes = [_normalize_ticker(t) for t in tickers]
    logger.info("get_multi_snapshot: %s", codes)

    try:
        ctx = _quote_ctx()
        ret, data = ctx.get_market_snapshot(codes)
        ctx.close()
    except Exception as exc:
        logger.exception("OpenD connection error")
        return json.dumps({"error": f"OpenD connection error: {exc}"})

    if ret != ft.RET_OK:
        return _ret_to_error(ret, data)

    records = _df_to_records(data)
    result = []
    for row in records:
        result.append({
            "ticker": row.get("code", ""),
            "name": row.get("name", ""),
            "last_price": row.get("last_price"),
            "change_val": row.get("change_val"),
            "change_rate": row.get("change_rate"),
            "volume": row.get("volume"),
            "turnover": row.get("turnover"),
            "market_cap": row.get("market_cap"),
            "pe_ratio": row.get("pe_ratio"),
            "pb_ratio": row.get("pb_ratio"),
            "52w_high": row.get("high_price_52weeks"),
            "52w_low": row.get("low_price_52weeks"),
            "dividend_yield": row.get("dividend_yield"),
        })
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting moomoo_server MCP (OpenD at %s:%d)", MOOMOO_HOST, MOOMOO_PORT)
    mcp.run()
