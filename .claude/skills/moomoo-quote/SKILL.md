---
name: moomoo-quote
description: Quick price check and key metrics for a stock using MooMoo API. Use when the user wants a brief stock summary, current price, or quick quote.
allowed-tools: Read, Bash, mcp__moomoo_server, mcp__financials_server
argument-hint: <TICKER>
---

# MooMoo Quick Quote

## Role
Provide a concise snapshot of a stock's current state.

## Input
Ticker symbol via `$ARGUMENTS`.

## Steps

1. Call MCP `moomoo_server.get_snapshot` for `US.$ARGUMENTS`
2. Call MCP `financials_server.get_fundamentals` for key ratios
3. Display a formatted summary:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  {TICKER} — {Company Name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Price:     ${current_price} ({change_pct}%)
  Volume:    {volume}
  Market Cap: ${market_cap}
  P/E:       {pe_ratio}
  P/B:       {pb_ratio}
  52W Range: ${low_52w} — ${high_52w}
  Dividend:  {div_yield}%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Output
Text-only summary displayed in Claude Code. No file generated.
