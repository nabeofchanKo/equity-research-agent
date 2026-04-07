---
name: moomoo-sector
description: Compare a stock against its sector peers using MooMoo API data. Use when the user wants sector analysis, peer comparison, or industry benchmarking.
allowed-tools: Read, Bash, mcp__moomoo_server, mcp__financials_server
argument-hint: <TICKER>
---

# MooMoo Sector Comparison

## Role
You are a sector analyst. Compare the target stock against its industry peers and highlight relative valuation.

## Input
Ticker symbol via `$ARGUMENTS`.

## Steps

### 1. Normalise ticker (same rules as moomoo-quote)

### 2. Find the stock's sector via MooMoo plates

```
mcp__moomoo_server__get_plate_for_stock(ticker=<normalised_ticker>)
```

Take the first industry plate from the result (`plate_code`).

### 3. Get stocks in that plate

```
mcp__moomoo_server__get_plate_stocks(plate_code=<plate_code>)
```

Select the top 10 stocks by listing order (MooMoo returns them sorted).
Exclude the target ticker itself.

### 4. Get snapshots for all peers (including the target)

```
mcp__moomoo_server__get_multi_snapshot(tickers=[target] + peers[:9])
```

### 5. Get detailed peer fundamentals

```
mcp__financials_server__get_peer_comparison(ticker=<normalised_ticker>, max_peers=9)
```

This returns a richer table with ROE, EPS, YTD return, and sector averages.

### 6. Build comparison table

Merge the MooMoo snapshot data with the financials peer comparison.

Sort all rows by market cap descending.

### 7. Display markdown table

Output a formatted markdown table with these columns:

| Ticker | Company | Mkt Cap | Price | P/E | P/B | ROE | EPS | Div % | YTD % |
|--------|---------|---------|-------|-----|-----|-----|-----|-------|-------|

Rules:
- **Bold** the target stock row
- After the table, print a "Sector Averages" row
- For each metric on the target row, note in parentheses whether it is:
  - `↑ premium` — target is >10% above sector average
  - `↓ discount` — target is >10% below sector average
  - `≈ in-line` — within ±10%

### 8. Brief commentary

Write 2-3 sentences summarising:
- Where the target stock ranks in the sector (top/mid/bottom quartile)
- Which metric shows the most notable premium or discount vs peers
- Overall relative attractiveness

## Output
Markdown table + brief commentary displayed in Claude Code terminal.
No HTML file generated.
