---
name: moomoo-dash
description: Generate a full visual equity research report for a given ticker using MooMoo OpenAPI data. Use when the user wants a comprehensive stock analysis dashboard, equity report, or stock overview with charts.
allowed-tools: Read, Write, Bash, Glob, Grep, mcp__moomoo_server, mcp__financials_server, mcp__news_sentiment_server
argument-hint: <TICKER>
---

# MooMoo Dashboard — Full Equity Research Report

## Role
You are a senior equity research analyst. Given a ticker symbol, you will collect data from multiple sources, run analysis, and produce a polished interactive HTML report.

## Input
The user provides a ticker symbol via `$ARGUMENTS` (e.g., `NVDA`, `AAPL`, `TSLA`).
Format it as MooMoo expects: `US.{TICKER}` for US stocks.

## Workflow

### Phase 1: Data Collection

1. **MooMoo Market Data** (via MCP: moomoo_server)
   - Call `get_snapshot` for current price, volume, turnover, P/E, P/B
   - Call `get_kline` for 180-day daily K-line data
   - Call `get_plate_for_stock` to identify the stock's sector
   - Call `get_plate_stocks` to get peer tickers in the same sector
   - Call `get_snapshot` for top 5-10 peers (for comparison)

2. **Fundamentals** (via MCP: financials_server)
   - Call `get_fundamentals` for ROE, EPS, dividend yield, revenue, net income
   - Call `get_earnings` for last 4 quarters of earnings data

3. **News & Sentiment** (via MCP: news_sentiment_server)
   - Call `get_news` for recent articles (last 7 days)
   - Call `score_sentiment` to compute sentiment scores

### Phase 2: Analysis

Using the `src/` Python modules:

1. **Technical Indicators**
   ```bash
   python -c "
   from src.technical_indicators import compute_all
   import json, pandas as pd
   kline = pd.read_json('session/kline_data.json')
   result = compute_all(kline)
   print(json.dumps(result, indent=2))
   "
   ```

2. **Sector Comparison**
   - Rank the target stock vs peers on: P/E, P/B, market cap, YTD return
   - Identify where the stock stands (percentile)

3. **Performance Benchmark**
   - Fetch benchmark K-line data (SPY, QQQ) for same period
   - Compute 1M/3M/6M/1Y cumulative returns for target vs benchmarks

### Phase 3: Report Generation

1. Run the report generator:
   ```bash
   python -c "
   from src.report_generator import generate_report
   generate_report(
       ticker='$ARGUMENTS',
       output_dir='outputs'
   )
   "
   ```

2. The HTML report is saved to `outputs/{TICKER}_{YYYY-MM-DD}_report.html`

## Output

- Tell the user the report has been generated
- Show the file path
- Display a brief text summary:
  - Current price and daily change
  - Overall signal (Bullish / Neutral / Bearish) based on technical + fundamental + sentiment
  - Top 3 key insights from the analysis
