---
name: moomoo-sector
description: Compare a stock against its sector peers using MooMoo API data. Use when the user wants sector analysis, peer comparison, or industry benchmarking.
allowed-tools: Read, Bash, mcp__moomoo_server, mcp__financials_server
argument-hint: <TICKER>
---

# MooMoo Sector Comparison

## Role
You are a sector analyst. Compare the target stock against its industry peers.

## Input
Ticker symbol via `$ARGUMENTS`.

## Steps

1. Call MCP `moomoo_server.get_plate_for_stock` to find the sector
2. Call MCP `moomoo_server.get_plate_stocks` to list sector peers
3. Call MCP `moomoo_server.get_snapshot` for top 10 peers by market cap
4. Call MCP `financials_server.get_fundamentals` for each peer

5. Build comparison table with columns:
   - Ticker, Company, Market Cap, Price, YTD %, P/E, P/B, ROE, Div Yield

6. Highlight where the target stock ranks in each metric

## Output
Display a formatted markdown table in Claude Code with the target stock row highlighted.
Indicate if the stock is trading at a premium or discount vs sector average for each metric.
