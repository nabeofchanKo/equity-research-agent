---
name: moomoo-quote
description: Quick price check and key metrics for a stock using MooMoo API. Use when the user wants a brief stock summary, current price, or quick quote.
allowed-tools: Read, Bash, mcp__moomoo_server, mcp__financials_server
argument-hint: <TICKER>
---

# MooMoo Quick Quote

## Role
Provide a concise snapshot of a stock's current state. Fast — no HTML file generated.

## Input
Ticker symbol via `$ARGUMENTS`.

## Steps

### 1. Normalise ticker
```
HK.00700 → HK.00700   (already prefixed)
00700    → HK.00700   (numeric → HK)
AAPL     → US.AAPL    (alpha → US)
US.AAPL  → US.AAPL    (already prefixed)
```

### 2. Fetch snapshot (MooMoo primary, yfinance fallback)

```
mcp__moomoo_server__get_snapshot(ticker=<normalised_ticker>)
```

Parse the JSON response.  MooMoo is tried first; if it returns a permission
or connection error the tool automatically retries with yfinance.  Check the
`"source"` field (`"moomoo"` or `"yfinance"`) to see which backend was used.
If `"error"` key is present and no fallback succeeded, show the error and stop.

### 3. Fetch fundamentals from yfinance

```
mcp__financials_server__get_fundamentals(ticker=<normalised_ticker>)
```

If this fails, use whatever fields were already in the MooMoo snapshot.

### 4. Display text summary

Format and print:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {TICKER} — {Company Name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Price:      {last_price} {currency}
  Change:     {change_val} ({change_rate}%)
  Volume:     {volume:,}
  Turnover:   {turnover}

  Market Cap: {market_cap}
  P/E:        {pe_ratio}
  P/B:        {pb_ratio}
  ROE:        {roe}
  EPS (TTM):  {eps_ttm}
  Div Yield:  {dividend_yield}
  Beta:       {beta}

  52W High:   {52w_high}
  52W Low:    {52w_low}

  Analyst:    {recommendation} · Target {analyst_target}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Use `—` for any field that is None or missing.
Format market cap with T/B/M suffix (e.g. 3.70T).
Change line: green arrow ▲ if positive, red arrow ▼ if negative.

## Output
Text-only summary displayed in Claude Code terminal. No file generated.
