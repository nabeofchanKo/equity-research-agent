"""
Sector Mapper

Converts ticker formats between MooMoo (HK.00700, US.AAPL) and yfinance
(0700.HK, AAPL) and provides sector-peer lookup using yfinance.
"""

import logging
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Curated sector → ticker maps
# Used as fallback when yfinance doesn't return enough same-industry peers.
# Keys match yfinance info["sector"] values.
# ---------------------------------------------------------------------------

_HK_SECTOR_PEERS: dict[str, list[str]] = {
    "Technology": ["0700.HK", "9988.HK", "9618.HK", "9999.HK", "3690.HK", "0268.HK", "2382.HK"],
    "Communication Services": ["0700.HK", "0762.HK", "0941.HK", "0315.HK"],
    "Consumer Cyclical": ["9988.HK", "9618.HK", "3690.HK", "0291.HK", "6862.HK"],
    "Financial Services": ["0005.HK", "0011.HK", "2318.HK", "1299.HK", "0939.HK", "1398.HK", "3988.HK"],
    "Industrials": ["0003.HK", "0006.HK", "0019.HK", "0101.HK", "0083.HK"],
    "Energy": ["0857.HK", "0883.HK", "0386.HK", "2688.HK"],
    "Real Estate": ["0016.HK", "0017.HK", "0083.HK", "1113.HK", "0012.HK"],
    "Healthcare": ["1177.HK", "6160.HK", "0241.HK", "0867.HK", "2269.HK"],
    "Consumer Defensive": ["0291.HK", "1929.HK", "0506.HK", "0220.HK"],
    "Utilities": ["0003.HK", "0006.HK", "0002.HK", "1038.HK"],
}

_US_SECTOR_PEERS: dict[str, list[str]] = {
    # Large-cap tech: semiconductors, software, cloud, hardware
    "Technology": [
        "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "INTC",
        "QCOM", "TXN", "AMAT", "MU", "KLAC", "LRCX", "ADBE", "NOW",
    ],
    # Mega-cap media, telco, streaming
    "Communication Services": [
        "GOOGL", "META", "NFLX", "DIS", "CMCSA", "T", "VZ",
        "SNAP", "PINS", "SPOT", "PARA", "WBD", "EA", "TTWO",
    ],
    # E-commerce, autos, restaurants, retail, travel
    "Consumer Cyclical": [
        "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW",
        "TGT", "BKNG", "UBER", "LYFT", "F", "GM", "RIVN", "DASH",
    ],
    # Banks, insurers, payment networks, brokers
    "Financial Services": [
        "BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS",
        "MS", "AXP", "C", "SCHW", "BLK", "SPGI", "CB", "PGR",
    ],
    # Pharma, biotech, medtech, managed care
    "Healthcare": [
        "LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT",
        "DHR", "PFE", "BMY", "AMGN", "GILD", "ISRG", "BSX", "SYK",
    ],
    # Aerospace, defense, machinery, logistics
    "Industrials": [
        "GE", "CAT", "HON", "UPS", "BA", "RTX", "LMT",
        "MMM", "DE", "FDX", "NOC", "GD", "EMR", "ETN", "PH",
    ],
    # Integrated, E&P, refining, services
    "Energy": [
        "XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX",
        "VLO", "OXY", "HAL", "PXD", "HES", "DVN", "WMB", "KMI",
    ],
    # REITs: industrial, cell towers, data centers, retail
    "Real Estate": [
        "PLD", "AMT", "EQIX", "CCI", "PSA", "O", "WELL",
        "DLR", "SPG", "EXR", "VICI", "AVB", "EQR", "MAA", "WY",
    ],
    # Staples: food, beverage, tobacco, household products
    "Consumer Defensive": [
        "WMT", "PG", "KO", "PEP", "COST", "PM", "MO",
        "CL", "GIS", "KMB", "KHC", "STZ", "HSY", "MKC", "SJM",
    ],
    # Electric, gas, multi-utility
    "Utilities": [
        "NEE", "DUK", "SO", "D", "EXC", "SRE", "AEP",
        "PCG", "ED", "ES", "WEC", "ETR", "PPL", "EIX", "AES",
    ],
    # Chemicals, metals, mining, packaging
    "Basic Materials": [
        "LIN", "APD", "SHW", "FCX", "NEM", "DOW", "DD",
        "PPG", "ALB", "CF", "NUE", "STLD", "AA", "BLL", "IP",
    ],
}


# ---------------------------------------------------------------------------
# Format conversion
# ---------------------------------------------------------------------------

def moomoo_to_yfinance(ticker: str) -> str:
    """
    Convert a MooMoo-format ticker to yfinance format.

    Examples:
        HK.00700  →  0700.HK
        HK.09988  →  9988.HK
        US.AAPL   →  AAPL
        US.BRK-B  →  BRK-B

    For HK tickers, MooMoo uses 5-digit zero-padded codes while yfinance
    uses 4-digit codes; this function converts between them.
    """
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("ticker must not be empty")

    if "." not in ticker:
        # No market prefix — assume US stock already in yfinance format
        return ticker

    market, code = ticker.split(".", 1)

    if market == "HK":
        # MooMoo: 5-digit (00700) → yfinance: 4-digit (0700)
        try:
            numeric = int(code)
            return f"{numeric:04d}.HK"
        except ValueError:
            return f"{code}.HK"

    if market == "US":
        return code  # AAPL, BRK-B, etc. — strip prefix

    # Unknown market prefix — return as-is with suffix
    return f"{code}.{market}"


def yfinance_to_moomoo(ticker: str) -> str:
    """
    Convert a yfinance-format ticker to MooMoo format.

    Examples:
        0700.HK  →  HK.00700
        9988.HK  →  HK.09988
        AAPL     →  US.AAPL
        BRK-B    →  US.BRK-B
    """
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("ticker must not be empty")

    if ticker.endswith(".HK"):
        code = ticker[:-3]
        try:
            numeric = int(code)
            return f"HK.{numeric:05d}"
        except ValueError:
            return f"HK.{code}"

    if "." not in ticker:
        # Plain US ticker
        return f"US.{ticker}"

    # Other exchange suffixes (e.g. .SZ, .SS) — not currently supported
    raise ValueError(f"Unsupported yfinance ticker format: {ticker}")


# ---------------------------------------------------------------------------
# Sector peer lookup
# ---------------------------------------------------------------------------

def get_sector_peers(
    ticker: str,
    max_peers: int = 10,
    include_self: bool = False,
) -> list[str]:
    """
    Return a list of yfinance tickers in the same sector as *ticker*.

    Strategy:
    1. Fetch the target stock's sector from yfinance.
    2. Look up the curated peer map for that sector.
    3. Remove the target stock itself unless include_self=True.
    4. Return up to max_peers tickers.

    Args:
        ticker:       yfinance-format ticker (e.g. "0700.HK", "AAPL").
        max_peers:    Maximum number of peers to return (default 10).
        include_self: Whether to include the target ticker in results.

    Returns:
        List of yfinance-format ticker strings.  Empty list if the sector
        cannot be determined or no peers are found.
    """
    try:
        info = yf.Ticker(ticker).info
    except Exception as exc:
        logger.warning("yfinance lookup failed for %s: %s", ticker, exc)
        return []

    sector: Optional[str] = info.get("sector")
    if not sector:
        logger.warning("No sector info for %s", ticker)
        return []

    logger.info("Sector for %s: %s", ticker, sector)

    # Select correct map based on exchange suffix
    if ticker.endswith(".HK"):
        peer_map = _HK_SECTOR_PEERS
    else:
        peer_map = _US_SECTOR_PEERS

    peers: list[str] = list(peer_map.get(sector, []))

    if not include_self:
        peers = [p for p in peers if p.upper() != ticker.upper()]

    return peers[:max_peers]
