# moomoo-dashboard

A Claude Code skill that generates **visual equity research reports** powered by MooMoo OpenAPI.  
Input a ticker → get a comprehensive interactive HTML dashboard with real-time market data, technicals, fundamentals, sector comparison, performance benchmarks, and sentiment analysis.

---

## Quick Start

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | Required for type hints and pandas 2.x |
| Claude Code CLI | Required to use the `/moomoo-dash` skill |
| [MooMoo OpenD](https://www.moomoo.com/download/OpenAPI) | Local gateway for real-time data — must be running |
| MooMoo Account | Free account provides HK LV1 market data |

> **Market data access:**  
> HK stocks (LV1) are available on a **free** MooMoo account.  
> US stocks require a **paid subscription** or qualifying account balance.  
> The demo and all defaults use `HK.00700` (Tencent) which works on free accounts.

### Install

```bash
cd moomoo-dashboard
pip install -r requirements.txt
```

### Start MooMoo OpenD

1. Download from [moomoo.com/download/OpenAPI](https://www.moomoo.com/download/OpenAPI)
2. Install, launch, and log in with your MooMoo account
3. OpenD listens on `127.0.0.1:11111` by default (configurable in `config/settings.yaml`)

---

## Two Ways to Generate Reports

### Method 1 — Claude Code Skill (recommended)

```bash
cd moomoo-dashboard
claude
```

Then inside Claude Code:

```
/moomoo-dash HK.00700       # Full equity research report
/moomoo-dash 00700          # Same — HK prefix inferred from numeric code
/moomoo-dash US.AAPL        # US stock (requires paid data rights)

/moomoo-quote HK.00700      # Quick price + key metrics (text only)
/moomoo-sector HK.00700     # Sector peer comparison table
```

The skill calls the three MCP servers via Claude's tool-use protocol, runs analysis, and generates `outputs/{TICKER}_{date}_report.html`.

### Method 2 — Command Line (standalone, no Claude needed)

```bash
# Single command — runs the full pipeline and writes the HTML report
python -m src.orchestrator HK.00700
python -m src.orchestrator US.AAPL
python -m src.orchestrator NVDA          # US prefix inferred from non-numeric code
python -m src.orchestrator 00700         # HK prefix inferred from numeric code

# Custom output directory
python -m src.orchestrator HK.00700 --output-dir ./my-reports
```

The orchestrator connects to OpenD and yfinance directly — no MCP or Claude required.

### View the sample report (no OpenD required)

```bash
python scripts/generate_sample_report.py
# Opens outputs/SAMPLE_HK.00700_report.html
```

---

## Report Sections

The generated single-file HTML report includes 7 interactive sections:

| # | Section | Contents |
|---|---|---|
| 1 | **Header & Summary** | Company info, current price, daily change %, overall signal gauge |
| 2 | **Price Chart** | 6-month candlestick with SMA 20/50/200, Bollinger Bands, volume |
| 3 | **Technical Indicators** | RSI, MACD (with histogram), Stochastic, support/resistance levels |
| 4 | **Fundamentals** | P/E, P/B, ROE, EPS, margins + quarterly earnings bar chart |
| 5 | **Sector Comparison** | Peer ranking table with color-coded relative valuation |
| 6 | **Performance Benchmark** | Stock vs index (^HSI or ^GSPC) over 1M / 3M / 6M / 1Y |
| 7 | **Sentiment & News** | Sentiment gauge + recent headlines with per-article scores |

---

## MCP Servers

Three MCP servers expose data as tools. They are registered in `.claude.json` and start automatically when Claude Code connects.

### `moomoo_server` — Real-time market data

Connects to MooMoo OpenD gateway. Provides live quotes, candlestick data, and sector/plate information.

| Tool | Description |
|---|---|
| `get_snapshot(ticker)` | Price, volume, P/E, P/B, 52W range, dividend yield |
| `get_kline(ticker, days, kline_type)` | OHLCV candlestick data (default 180 days, daily) |
| `get_plate_list(market)` | All industry sector plates for a market |
| `get_plate_stocks(plate_code)` | All stocks in a sector plate |
| `get_plate_for_stock(ticker)` | Which plates a stock belongs to |
| `get_multi_snapshot(tickers)` | Batch snapshots for peer comparison |

### `financials_server` — Fundamental data

Uses yfinance (Yahoo Finance). Works for both HK and US stocks.

| Tool | Description |
|---|---|
| `get_fundamentals(ticker)` | P/E, P/B, ROE, EPS, margins, beta, analyst target |
| `get_earnings(ticker)` | Last 4 quarters: revenue, net income, EPS |
| `get_peer_comparison(ticker, max_peers)` | Side-by-side fundamental comparison vs sector peers |
| `get_performance(ticker, benchmark)` | 1M/3M/6M/1Y cumulative returns vs index |

### `news_sentiment_server` — News & sentiment

Uses yfinance news feed + keyword-based sentiment scoring.

| Tool | Description |
|---|---|
| `get_news(ticker, days)` | Recent news articles with title, publisher, date, pre-scored sentiment |
| `score_sentiment(articles_json)` | Score a batch of articles; returns per-article and overall score |

---

## Skills

| Skill | Command | Description | Tools used |
|---|---|---|---|
| `moomoo-dash` | `/moomoo-dash <TICKER>` | Full equity research report (HTML) | All 3 servers |
| `moomoo-quote` | `/moomoo-quote <TICKER>` | Quick price + key metrics (text) | moomoo + financials |
| `moomoo-sector` | `/moomoo-sector <TICKER>` | Sector peer comparison table | moomoo + financials |

---

## Architecture

```
User runs /moomoo-dash HK.00700
          │
          ▼
    Claude Code (skill orchestration)
          │
    ┌─────┴──────────────────────────┐
    │                                │
    ▼                                ▼
moomoo_server              financials_server
(MooMoo OpenD)             (yfinance / Yahoo)
    │                                │
    │  snapshot, kline,              │  fundamentals, earnings,
    │  plates, peers                 │  performance, peer comparison
    │                                │
    └──────────┬─────────────────────┘
               │
               ▼
    news_sentiment_server
    (yfinance news + keyword scoring)
               │
               ▼
    src/technical_indicators.py
    (RSI, MACD, Bollinger, SMA, Stochastic)
               │
               ▼
    src/report_generator.py
    (Jinja2 + Plotly → single HTML)
               │
               ▼
    outputs/{TICKER}_{date}_report.html
```

---

## Configuration

`config/settings.yaml`:

```yaml
moomoo:
  host: "127.0.0.1"
  port: 11111
  default_kline_days: 180

technical:
  sma_periods: [20, 50, 200]
  rsi_period: 14
  macd_fast: 12
  macd_slow: 26
  macd_signal: 9
  bollinger_period: 20
  bollinger_std: 2

sentiment:
  lookback_days: 7
```

---

## Project Structure

```
moomoo-dashboard/
├── README.md
├── requirements.txt
├── setup.py
├── pytest.ini
├── .claude.json                    ← MCP server registration
├── config/settings.yaml
├── mcp_servers/
│   ├── moomoo_server/server.py     ← 6 MooMoo tools
│   ├── financials_server/server.py ← 4 yfinance tools
│   └── news_sentiment_server/server.py ← 2 sentiment tools
├── src/
│   ├── technical_indicators.py     ← RSI/MACD/BB/Stoch/SMA
│   ├── sector_mapper.py            ← Ticker format conversion + peer lookup
│   ├── report_generator.py         ← Jinja2 + Plotly HTML report
│   ├── orchestrator.py             ← CLI pipeline (no MCP needed)
│   └── utils.py
├── templates/report.html           ← Dark-theme Jinja2 template
├── scripts/
│   └── generate_sample_report.py  ← Generates outputs/SAMPLE_*.html
├── outputs/
│   └── SAMPLE_HK.00700_report.html ← Pre-generated sample
├── tests/
│   ├── test_utils.py
│   ├── test_technical_indicators.py
│   ├── test_sector_mapper.py
│   ├── test_financials_server.py
│   ├── test_moomoo_server.py
│   ├── test_report_generator.py
│   └── test_integration.py         ← @pytest.mark.integration
└── .claude/
    └── skills/
        ├── moomoo-dash/SKILL.md
        ├── moomoo-quote/SKILL.md
        └── moomoo-sector/SKILL.md
```

---

## Running Tests

```bash
# Unit tests only (no OpenD, no internet required)
pytest -m "not integration" -q

# All tests including integration (OpenD + internet required)
pytest -m integration -v

# Single test file
pytest tests/test_technical_indicators.py -q
pytest tests/test_report_generator.py -q
```

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Market data | moomoo-api (Python SDK) | Real-time quotes, K-line, sector plates |
| Fundamentals | yfinance | P/E, ROE, earnings, peer data |
| Analysis | pandas, numpy | Technical indicator computation |
| Charts | Plotly | Interactive embedded charts |
| Templating | Jinja2 | HTML report generation |
| Sentiment | yfinance news + keyword scoring | News retrieval + scoring |
| MCP | mcp Python SDK (FastMCP) | Tool server protocol |
| Testing | pytest | Unit + integration tests |
