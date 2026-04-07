---
name: moomoo-dash
description: Generate a full visual equity research report for a given ticker using MooMoo OpenAPI data. Use when the user wants a comprehensive stock analysis dashboard, equity report, or stock overview with charts.
allowed-tools: Read, Write, Bash, Glob, Grep, mcp__moomoo_server, mcp__financials_server, mcp__news_sentiment_server
argument-hint: <TICKER>
---

# MooMoo Dashboard — Full Equity Research Report

## Role
You are a senior equity research analyst. Given a ticker symbol you collect real market data, run analysis, and produce a polished interactive HTML report.

## Input
Ticker symbol via `$ARGUMENTS`.
- HK stocks: plain code like `00700` or `HK.00700` → normalise to `HK.00700`
- US stocks: plain symbol like `AAPL` or `US.AAPL` → normalise to `US.AAPL`
- Default market is **HK**. If no prefix and code looks numeric, assume HK.

## Workflow

### Step 1 — Normalise the ticker
```python
ticker = "$ARGUMENTS".strip().upper()
if "." not in ticker:
    # numeric → HK, alpha → US
    ticker = f"HK.{ticker}" if ticker.isnumeric() else f"US.{ticker}"
```

### Step 2 — Collect market data (MooMoo MCP)

Call these tools. If any fails, log a warning and continue with empty/None for that field.

```
mcp__moomoo_server__get_snapshot(ticker=ticker)
mcp__moomoo_server__get_kline(ticker=ticker, days=180, kline_type="K_DAY")
mcp__moomoo_server__get_plate_for_stock(ticker=ticker)
```

From the plate result, take the first plate_code and call:
```
mcp__moomoo_server__get_plate_stocks(plate_code=<first_plate_code>)
```

From plate_stocks, pick up to 8 peer tickers (exclude the target), then:
```
mcp__moomoo_server__get_multi_snapshot(tickers=[...peer tickers...])
```

### Step 3 — Collect fundamentals (Financials MCP)

```
mcp__financials_server__get_fundamentals(ticker=ticker)
mcp__financials_server__get_earnings(ticker=ticker)
mcp__financials_server__get_peer_comparison(ticker=ticker, max_peers=8)
mcp__financials_server__get_performance(ticker=ticker)
```

### Step 4 — Collect news & sentiment (optional)

Wrap in try/except. If the server is not running, skip gracefully.

```
mcp__news_sentiment_server__get_news(ticker=ticker, days=7)
mcp__news_sentiment_server__score_sentiment(articles_json=<articles_json_string>)
```

If news fails, set `sentiment = None`.

### Step 5 — Compute technical indicators

Parse the kline records from Step 2 into a DataFrame and run:

```bash
python -c "
import json, sys, pandas as pd
from src.technical_indicators import compute_all

kline = json.loads('''$KLINE_JSON''')
records = kline.get('records', [])
if not records:
    print(json.dumps({'signal_score': 0, 'signal_label': 'Neutral', 'sma': {}, 'rsi': {}, 'macd': {}, 'bollinger': {}, 'stochastic': {}, 'support_resistance': {'support':[],'resistance':[]}, 'data_points': 0, 'latest_price': 0}))
    sys.exit(0)

df = pd.DataFrame(records)
df = df.rename(columns={'time_key': 'date', 'trade_vol': 'volume', 'trade_val': 'turnover'})
result = compute_all(df)
print(json.dumps(result))
"
```

Or pass the data directly via a temp file if the JSON is large.

### Step 6 — Generate the HTML report

```bash
python -c "
import json, sys
sys.path.insert(0, '.')
from src.report_generator import generate_report

snapshot      = $SNAPSHOT_JSON
kline_records = $KLINE_RECORDS
fundamentals  = $FUNDAMENTALS_JSON
earnings      = $EARNINGS_JSON
technicals    = $TECHNICALS_JSON
peers         = $PEERS_JSON
performance   = $PERFORMANCE_JSON
sentiment     = $SENTIMENT_JSON  # None if unavailable

path = generate_report(
    ticker='$TICKER',
    snapshot=snapshot,
    kline_records=kline_records,
    fundamentals=fundamentals,
    earnings=earnings,
    technicals=technicals,
    peers=peers,
    performance=performance,
    sentiment=sentiment,
    output_dir='outputs',
)
print(path)
"
```

**Preferred shortcut — use the orchestrator:**
```bash
python -m src.orchestrator $ARGUMENTS
```
The orchestrator handles all data collection, analysis, and report generation in one call.

### Step 7 — Show summary

After the report is written, display:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {TICKER} — {Company Name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Report saved to: outputs/{TICKER}_{date}_report.html

  Price:   {last_price} ({change_pct}%)
  Signal:  {signal_label}  (score: {signal_score:.2f})
  RSI:     {rsi_value}
  Market Cap: {market_cap}
  P/E:     {pe_ratio}

  Top insights:
  1. {derive from signal score / SMA position}
  2. {derive from RSI / MACD cross}
  3. {derive from performance vs benchmark}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Error Handling

| Failure | Action |
|---|---|
| OpenD not running | Error clearly: "MooMoo OpenD is not running. Start OpenD and retry." |
| Ticker not found in snapshot | Warn and try to continue with yfinance-only data |
| Kline empty / too short | Technicals will be sparse; report still generates |
| news_sentiment_server offline | Skip sentiment section (report still renders) |
| financials_server offline | Use MooMoo snapshot ratios as fallback |

## Output
- HTML report at `outputs/{TICKER}_{YYYY-MM-DD}_report.html`
- Brief text summary in Claude Code terminal
