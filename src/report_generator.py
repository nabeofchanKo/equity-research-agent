"""
Report Generator

Combines snapshot, K-line, fundamentals, technical indicators, peer comparison,
performance, and sentiment data into a single self-contained interactive HTML report.

Entry point: generate_report(ticker, snapshot, kline_records, fundamentals,
                              earnings, technicals, peers, performance,
                              sentiment, output_dir)
"""

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader
from plotly.subplots import make_subplots

from src.technical_indicators import _bollinger, _macd, _rsi, _sma, _stochastic

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Design tokens (must stay in sync with CSS custom properties in the template)
# ─────────────────────────────────────────────────────────────────────────────

C = {
    "paper":    "rgba(0,0,0,0)",
    "plot_bg":  "rgba(17,24,39,0.55)",
    "green":    "#00d68f",
    "red":      "#ff3d71",
    "blue":     "#3d8bff",
    "yellow":   "#ffb700",
    "purple":   "#a855f7",
    "text":     "#e8edf5",
    "muted":    "#8b9dc3",
    "grid":     "rgba(99,120,168,0.09)",
    "sma20":    "#ffb700",
    "sma50":    "#3d8bff",
    "sma200":   "#a855f7",
    "bb_fill":  "rgba(61,139,255,0.06)",
    "card":     "#111827",
}

_BASE_LAYOUT = dict(
    paper_bgcolor=C["paper"],
    plot_bgcolor=C["plot_bg"],
    font=dict(family="Inter, system-ui, sans-serif", color=C["muted"], size=11),
    margin=dict(l=8, r=8, t=28, b=8),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=10, color=C["muted"]),
        orientation="h",
        yanchor="bottom", y=1.01,
        xanchor="left", x=0,
    ),
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor="#1a2235",
        bordercolor=C["grid"],
        font=dict(family="Inter, monospace", size=11, color=C["text"]),
    ),
)

_XAXIS = dict(
    gridcolor=C["grid"], showgrid=True,
    zeroline=False, showline=False,
    tickfont=dict(size=10, color=C["muted"]),
    rangeslider=dict(visible=False),
)
_YAXIS = dict(
    gridcolor=C["grid"], showgrid=True,
    zeroline=False, showline=False,
    tickfont=dict(size=10, color=C["muted"]),
    side="right",
)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fig_json(fig: go.Figure) -> str:
    return fig.to_json()


def _kline_to_df(records: list[dict]) -> pd.DataFrame:
    """Convert MooMoo get_kline records into a clean, sorted DataFrame."""
    df = pd.DataFrame(records)
    if df.empty:
        return df
    date_col = next((c for c in ("time_key", "Date", "date") if c in df.columns), None)
    if date_col:
        df["date"] = pd.to_datetime(df[date_col])
        df = df.sort_values("date").reset_index(drop=True)
    if "trade_vol" in df.columns and "volume" not in df.columns:
        df["volume"] = df["trade_vol"]
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Chart builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_price_chart(df: pd.DataFrame, technicals: dict) -> str:
    if df.empty:
        return go.Figure().to_json()

    dates = df["date"] if "date" in df.columns else df.index
    close = df["close"].astype(float)
    high  = df["high"].astype(float)
    low   = df["low"].astype(float)
    open_ = df["open"].astype(float)

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.76, 0.24],
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=dates, open=open_, high=high, low=low, close=close,
        name="OHLC",
        increasing=dict(line=dict(color=C["green"], width=1), fillcolor=C["green"]),
        decreasing=dict(line=dict(color=C["red"],   width=1), fillcolor=C["red"]),
        showlegend=False,
    ), row=1, col=1)

    # Bollinger Bands
    bb_upper, bb_mid, bb_lower = _bollinger(close, 20, 2.0)
    fig.add_trace(go.Scatter(
        x=dates, y=bb_upper, name="BB Upper",
        line=dict(color=C["blue"], width=0.8, dash="dot"),
        showlegend=True, hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=dates, y=bb_lower, name="BB Lower",
        line=dict(color=C["blue"], width=0.8, dash="dot"),
        fill="tonexty", fillcolor=C["bb_fill"],
        showlegend=False, hoverinfo="skip",
    ), row=1, col=1)

    # SMA lines
    for period, color in [(20, C["sma20"]), (50, C["sma50"]), (200, C["sma200"])]:
        sma = _sma(close, period)
        fig.add_trace(go.Scatter(
            x=dates, y=sma, name=f"SMA{period}",
            line=dict(color=color, width=1.3),
            hoverinfo="skip",
        ), row=1, col=1)

    # Support / Resistance
    sr = technicals.get("support_resistance", {})
    for lvl in sr.get("support", []):
        fig.add_hline(y=lvl, row=1, col=1,
                      line=dict(color=C["green"], width=0.7, dash="dash"))
    for lvl in sr.get("resistance", []):
        fig.add_hline(y=lvl, row=1, col=1,
                      line=dict(color=C["red"], width=0.7, dash="dash"))

    # Volume
    if "volume" in df.columns:
        vol = df["volume"].astype(float)
        bar_colors = [C["green"] if c >= o else C["red"]
                      for c, o in zip(df["close"], df["open"])]
        fig.add_trace(go.Bar(
            x=dates, y=vol, name="Volume",
            marker=dict(color=bar_colors, opacity=0.65),
            showlegend=False,
            hovertemplate="%{y:,.0f}<extra>Vol</extra>",
        ), row=2, col=1)

    fig.update_layout(
        **_BASE_LAYOUT,
        height=530,
        xaxis=dict(**_XAXIS),
        xaxis2=dict(**_XAXIS),
        yaxis=dict(**_YAXIS),
        yaxis2=dict(**_YAXIS),
    )
    return _fig_json(fig)


def _build_rsi_chart(df: pd.DataFrame, period: int = 14) -> str:
    if df.empty:
        return go.Figure().to_json()
    dates = df["date"] if "date" in df.columns else df.index
    rsi = _rsi(df["close"].astype(float), period)

    fig = go.Figure()
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(255,61,113,0.07)", line_width=0)
    fig.add_hrect(y0=0,  y1=30,  fillcolor="rgba(0,214,143,0.07)", line_width=0)
    for y, color in [(70, C["red"]), (30, C["green"]), (50, C["muted"])]:
        fig.add_hline(y=y, line=dict(color=color, width=0.7, dash="dot"))

    fig.add_trace(go.Scatter(
        x=dates, y=rsi, name=f"RSI({period})",
        line=dict(color=C["yellow"], width=1.6),
        hovertemplate="RSI: %{y:.1f}<extra></extra>",
    ))
    fig.update_layout(
        **_BASE_LAYOUT, height=210,
        yaxis=dict(**_YAXIS, range=[0, 100], dtick=25),
        xaxis=dict(**_XAXIS),
    )
    return _fig_json(fig)


def _build_macd_chart(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> str:
    if df.empty:
        return go.Figure().to_json()
    dates = df["date"] if "date" in df.columns else df.index
    close = df["close"].astype(float)
    macd_line, signal_line, hist = _macd(close, fast, slow, signal)

    bar_colors = [C["green"] if v >= 0 else C["red"] for v in hist.fillna(0)]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=dates, y=hist, name="Histogram",
        marker=dict(color=bar_colors, opacity=0.7),
        hovertemplate="Hist: %{y:.5f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=dates, y=macd_line, name=f"MACD({fast},{slow})",
        line=dict(color=C["blue"], width=1.6),
        hovertemplate="MACD: %{y:.5f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=dates, y=signal_line, name=f"Signal({signal})",
        line=dict(color=C["yellow"], width=1.3),
        hovertemplate="Signal: %{y:.5f}<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color=C["muted"], width=0.5))
    fig.update_layout(
        **_BASE_LAYOUT, height=210,
        yaxis=dict(**_YAXIS),
        xaxis=dict(**_XAXIS),
    )
    return _fig_json(fig)


def _build_stoch_chart(df: pd.DataFrame, k: int = 14, d: int = 3) -> str:
    if df.empty:
        return go.Figure().to_json()
    dates = df["date"] if "date" in df.columns else df.index
    stoch_k, stoch_d = _stochastic(
        df["high"].astype(float),
        df["low"].astype(float),
        df["close"].astype(float),
        k, d,
    )
    fig = go.Figure()
    fig.add_hrect(y0=80, y1=100, fillcolor="rgba(255,61,113,0.07)", line_width=0)
    fig.add_hrect(y0=0,  y1=20,  fillcolor="rgba(0,214,143,0.07)", line_width=0)
    for y, color in [(80, C["red"]), (20, C["green"])]:
        fig.add_hline(y=y, line=dict(color=color, width=0.7, dash="dot"))

    fig.add_trace(go.Scatter(
        x=dates, y=stoch_k, name=f"%K({k})",
        line=dict(color=C["blue"], width=1.6),
        hovertemplate="%%K: %{y:.1f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=dates, y=stoch_d, name=f"%D({d})",
        line=dict(color=C["yellow"], width=1.3),
        hovertemplate="%%D: %{y:.1f}<extra></extra>",
    ))
    fig.update_layout(
        **_BASE_LAYOUT, height=200,
        yaxis=dict(**_YAXIS, range=[0, 100], dtick=25),
        xaxis=dict(**_XAXIS),
    )
    return _fig_json(fig)


def _build_earnings_chart(quarters: list[dict]) -> str:
    if not quarters:
        return go.Figure().to_json()

    periods   = [q.get("period", "")  for q in quarters]
    revenues  = [q.get("revenue")     for q in quarters]
    net_inc   = [q.get("net_income")  for q in quarters]

    def _scale(vals):
        cleaned = [v for v in vals if v is not None]
        if not cleaned:
            return vals, ""
        mx = max(abs(v) for v in cleaned)
        if mx >= 1e9:  return [v / 1e9  if v else None for v in vals], "B"
        if mx >= 1e6:  return [v / 1e6  if v else None for v in vals], "M"
        return vals, ""

    rev_s, rev_u = _scale(revenues)
    ni_s,  ni_u  = _scale(net_inc)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=periods[::-1], y=rev_s[::-1], name=f"Revenue ({rev_u})",
        marker=dict(color=C["blue"], opacity=0.8),
        hovertemplate=f"%{{y:.2f}}{rev_u}<extra>Revenue</extra>",
    ))
    fig.add_trace(go.Bar(
        x=periods[::-1], y=ni_s[::-1], name=f"Net Income ({ni_u})",
        marker=dict(color=C["green"], opacity=0.85),
        hovertemplate=f"%{{y:.2f}}{ni_u}<extra>Net Income</extra>",
    ))
    fig.update_layout(
        **_BASE_LAYOUT, height=280, barmode="group",
        yaxis=dict(**_YAXIS),
        xaxis=dict(**_XAXIS, type="category"),
    )
    return _fig_json(fig)


def _build_performance_chart(performance_data: list[dict]) -> str:
    if not performance_data:
        return go.Figure().to_json()

    labels     = [r.get("period", "")              for r in performance_data]
    tick_rets  = [r.get("ticker_return_pct")        for r in performance_data]
    bench_rets = [r.get("benchmark_return_pct")     for r in performance_data]
    bench_name = performance_data[0].get("benchmark", "Benchmark")

    def _colors(vals):
        return [C["green"] if (v is not None and v >= 0) else C["red"] for v in vals]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=tick_rets, name="Stock",
        marker=dict(color=_colors(tick_rets), opacity=0.88),
        hovertemplate="%{y:.2f}%<extra>Stock</extra>",
    ))
    fig.add_trace(go.Bar(
        x=labels, y=bench_rets, name=bench_name,
        marker=dict(color=C["blue"], opacity=0.5),
        hovertemplate="%{y:.2f}%<extra>Benchmark</extra>",
    ))
    fig.add_hline(y=0, line=dict(color=C["muted"], width=0.7))
    fig.update_layout(
        **_BASE_LAYOUT, height=270, barmode="group",
        yaxis=dict(**_YAXIS, ticksuffix="%"),
        xaxis=dict(**_XAXIS, type="category"),
    )
    return _fig_json(fig)


def _build_gauge(value: float, label: str,
                 lo_color: str = "#ff3d71", hi_color: str = "#00d68f") -> str:
    """Generic [0-100] gauge."""
    color = hi_color if value >= 60 else (lo_color if value <= 40 else C["yellow"])
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number=dict(font=dict(size=30, color=color), valueformat=".0f"),
        gauge=dict(
            axis=dict(range=[0, 100], tickvals=[0, 25, 50, 75, 100],
                      tickfont=dict(size=9, color=C["muted"])),
            bar=dict(color=color, thickness=0.55),
            bgcolor=C["card"],
            bordercolor=C["grid"], borderwidth=1,
            steps=[
                dict(range=[0,  30], color="rgba(255,61,113,0.18)"),
                dict(range=[30, 45], color="rgba(255,183,0,0.08)"),
                dict(range=[45, 55], color="rgba(255,183,0,0.12)"),
                dict(range=[55, 70], color="rgba(0,214,143,0.08)"),
                dict(range=[70, 100], color="rgba(0,214,143,0.18)"),
            ],
        ),
        title=dict(text=label, font=dict(size=13, color=color)),
        domain=dict(x=[0, 1], y=[0, 1]),
    ))
    base = {k: v for k, v in _BASE_LAYOUT.items() if k != "margin"}
    fig.update_layout(**base, height=230, margin=dict(l=20, r=20, t=35, b=10), showlegend=False)
    return _fig_json(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers (also exposed to Jinja2 globals)
# ─────────────────────────────────────────────────────────────────────────────

def fmt_num(val: Any, decimals: int = 2, suffix: str = "", prefix: str = "") -> str:
    if val is None:
        return "—"
    try:
        return f"{prefix}{float(val):,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(val)


def fmt_large(val: Any) -> str:
    if val is None:
        return "—"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return str(val)
    if abs(v) >= 1e12: return f"{v/1e12:.2f}T"
    if abs(v) >= 1e9:  return f"{v/1e9:.2f}B"
    if abs(v) >= 1e6:  return f"{v/1e6:.2f}M"
    return f"{v:,.0f}"


def fmt_pct(val: Any, decimals: int = 2) -> str:
    """Format a decimal (0.22) or percentage (22.0) as '22.00%'."""
    if val is None:
        return "—"
    try:
        v = float(val)
        if abs(v) < 5:      # assume decimal form (e.g. 0.22 → 22%)
            v *= 100
        return f"{v:.{decimals}f}%"
    except (TypeError, ValueError):
        return str(val)


def _compare_class(val: Any, avg: Any, lower_is_better: bool = False) -> str:
    if val is None or avg is None:
        return ""
    is_above = float(val) > float(avg)
    if lower_is_better:
        return "cell-below" if is_above else "cell-above"
    return "cell-above" if is_above else "cell-below"


def _prepare_peers(peers: dict) -> list[dict]:
    rows = []
    averages = peers.get("sector_averages", {})
    for p in peers.get("peers", []):
        row = dict(p)
        row["pe_class"]    = _compare_class(p.get("pe_ratio"),      averages.get("pe_ratio"),      lower_is_better=True)
        row["roe_class"]   = _compare_class(p.get("roe"),           averages.get("roe"),            lower_is_better=False)
        row["ytd_class"]   = _compare_class(p.get("ytd_return_pct"),averages.get("ytd_return_pct"), lower_is_better=False)
        row["div_class"]   = _compare_class(p.get("dividend_yield"),averages.get("dividend_yield"),  lower_is_better=False)
        row["pe_fmt"]      = fmt_num(p.get("pe_ratio"))
        row["pb_fmt"]      = fmt_num(p.get("pb_ratio"))
        row["roe_fmt"]     = fmt_pct(p.get("roe"))
        row["eps_fmt"]     = fmt_num(p.get("eps_ttm"), 3)
        row["div_fmt"]     = fmt_pct(p.get("dividend_yield"))
        row["ytd_fmt"]     = fmt_num(p.get("ytd_return_pct"), 2, suffix="%") if p.get("ytd_return_pct") is not None else "—"
        row["mktcap_fmt"]  = fmt_large(p.get("market_cap"))
        rows.append(row)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(
    ticker: str,
    snapshot: dict,
    kline_records: list[dict],
    fundamentals: dict,
    earnings: dict,
    technicals: dict,
    peers: dict,
    performance: dict,
    sentiment: Optional[dict] = None,
    output_dir: str = "outputs",
) -> str:
    """
    Render a self-contained interactive HTML equity research report.

    Args:
        ticker:        MooMoo-format ticker (e.g. "HK.00700", "US.AAPL").
        snapshot:      Parsed output of moomoo_server.get_snapshot.
        kline_records: List of dicts from moomoo_server.get_kline["records"].
        fundamentals:  Parsed output of financials_server.get_fundamentals.
        earnings:      Parsed output of financials_server.get_earnings.
        technicals:    Output of technical_indicators.compute_all.
        peers:         Parsed output of financials_server.get_peer_comparison.
        performance:   Parsed output of financials_server.get_performance.
        sentiment:     Optional dict {"score": float, "label": str, "articles": [...]}.
        output_dir:    Output directory (default "outputs").

    Returns:
        Absolute path to the generated HTML file.
    """
    logger.info("Generating report for %s", ticker)
    kline_df = _kline_to_df(kline_records)

    # Signal / sentiment gauge values (0-100 scale)
    sig_score = technicals.get("signal_score", 0.0) or 0.0
    sig_gauge = round((sig_score + 1) / 2 * 100)
    sig_label = technicals.get("signal_label", "Neutral")

    sent_raw = (sentiment or {}).get("score", 0.0) or 0.0
    sent_gauge = round((sent_raw + 1) / 2 * 100)
    sent_label = (sentiment or {}).get("label", "Neutral")

    charts = {
        "price":       _build_price_chart(kline_df, technicals),
        "rsi":         _build_rsi_chart(kline_df),
        "macd":        _build_macd_chart(kline_df),
        "stoch":       _build_stoch_chart(kline_df),
        "earnings":    _build_earnings_chart(earnings.get("quarters", [])),
        "performance": _build_performance_chart(performance.get("performance", [])),
        "signal":      _build_gauge(sig_gauge, sig_label),
        "sentiment":   _build_gauge(sent_gauge, sent_label),
    }

    clean_ticker  = ticker.split(".")[-1] if "." in ticker else ticker
    company_name  = snapshot.get("name") or fundamentals.get("name") or clean_ticker
    change_rate   = float(snapshot.get("change_rate") or 0.0)
    last_price    = snapshot.get("last_price") or technicals.get("latest_price")

    ctx = dict(
        ticker           = clean_ticker,
        full_ticker      = ticker,
        company_name     = company_name,
        date             = date.today().isoformat(),
        sector           = fundamentals.get("sector") or "",
        industry         = fundamentals.get("industry") or "",
        currency         = fundamentals.get("currency") or "",
        last_price       = fmt_num(last_price, 3),
        change_rate      = fmt_num(abs(change_rate), 2, suffix="%"),
        change_positive  = change_rate >= 0,
        signal_label     = sig_label,
        signal_score     = sig_score,
        # ── Key metric strip
        market_cap       = fmt_large(snapshot.get("market_cap") or fundamentals.get("market_cap")),
        pe_ratio         = fmt_num(fundamentals.get("pe_ratio") or snapshot.get("pe_ratio")),
        pb_ratio         = fmt_num(fundamentals.get("pb_ratio") or snapshot.get("pb_ratio")),
        div_yield        = fmt_pct(fundamentals.get("dividend_yield") or snapshot.get("dividend_yield")),
        beta             = fmt_num(fundamentals.get("beta")),
        high_52w         = fmt_num(fundamentals.get("52w_high") or snapshot.get("52w_high"), 3),
        low_52w          = fmt_num(fundamentals.get("52w_low")  or snapshot.get("52w_low"),  3),
        # ── Technicals scalars (for annotation cards)
        rsi_value        = fmt_num(technicals.get("rsi",        {}).get("value")),
        rsi_period       = technicals.get("rsi", {}).get("period", 14),
        stoch_k          = fmt_num(technicals.get("stochastic", {}).get("k")),
        stoch_d          = fmt_num(technicals.get("stochastic", {}).get("d")),
        bb_upper         = fmt_num(technicals.get("bollinger",  {}).get("upper"), 3),
        bb_lower         = fmt_num(technicals.get("bollinger",  {}).get("lower"), 3),
        bb_bw            = fmt_num(technicals.get("bollinger",  {}).get("bandwidth"), 4),
        sma              = technicals.get("sma", {}),
        macd_val         = technicals.get("macd", {}).get("macd"),
        macd_signal_val  = technicals.get("macd", {}).get("signal"),
        support_levels   = technicals.get("support_resistance", {}).get("support", []),
        resistance_levels= technicals.get("support_resistance", {}).get("resistance", []),
        # ── Fundamentals
        roe              = fmt_pct(fundamentals.get("roe")),
        eps_ttm          = fmt_num(fundamentals.get("eps_ttm"), 3),
        eps_forward      = fmt_num(fundamentals.get("eps_forward"), 3),
        profit_margin    = fmt_pct(fundamentals.get("profit_margin")),
        revenue_ttm      = fmt_large(fundamentals.get("revenue_ttm")),
        analyst_target   = fmt_num(fundamentals.get("analyst_target"), 3),
        recommendation   = (fundamentals.get("recommendation") or "").replace("-", " ").title(),
        debt_to_equity   = fmt_num(fundamentals.get("debt_to_equity")),
        current_ratio    = fmt_num(fundamentals.get("current_ratio")),
        book_value       = fmt_num(fundamentals.get("book_value"), 2),
        # ── Earnings / peers / performance / sentiment
        earnings_quarters= earnings.get("quarters", []),
        peers_rows       = _prepare_peers(peers),
        sector_averages  = peers.get("sector_averages", {}),
        performance_rows = performance.get("performance", []),
        benchmark        = performance.get("benchmark", ""),
        sentiment_label  = sent_label,
        news_articles    = (sentiment or {}).get("articles", []),
        # ── Charts JSON (rendered with | safe)
        charts           = charts,
    )

    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=False)
    env.globals.update(fmt_num=fmt_num, fmt_large=fmt_large, fmt_pct=fmt_pct)
    html = env.get_template("report.html").render(**ctx)

    out_dir  = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{clean_ticker}_{date.today().isoformat()}_report.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info("Report written → %s", out_path)
    return str(out_path)
