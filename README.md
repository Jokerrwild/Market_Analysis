# Market Pulse

Market Pulse is a self-contained cryptocurrency analysis app that runs the hybrid intelligence process described in `agents/crypto_hybrid_intelligence_agent.md`.

It collects crypto and macro market data, applies a Bayesian-style regime model, adds rule-based contextual interpretation, and saves each analysis as Markdown and JSON.

## Quick Start

Run one analysis:

```powershell
python -m market_pulse run
```

Run the local dashboard:

```powershell
python -m market_pulse dashboard
```

Then open:

```text
http://127.0.0.1:8765
```

On Windows, you can double-click `Start_Market_Pulse.bat` from the project folder. The browser will open automatically, and the dashboard Exit button will stop the local server.

To start without showing a terminal window, double-click `Start_Market_Pulse_Hidden.vbs` instead. Keep `Start_Market_Pulse.bat` available for troubleshooting because it shows startup messages.

The dashboard opens from the SQLite database first so the page loads quickly. Press the dashboard refresh button to force a fresh live market collection; this can take longer when external market APIs are slow.

Run every hour:

```powershell
python -m market_pulse watch --interval-minutes 60
```

Show database collection status:

```powershell
python -m market_pulse db-stats
```

Run at specific times each day:

```powershell
python -m market_pulse watch --times 09:30,12:00,16:00,20:00
```

Run every 90 minutes only between 8 AM and 9 PM:

```powershell
python -m market_pulse watch --interval-minutes 90 --between 08:00-21:00
```

Reports are written to `reports/`. The latest Markdown report is also copied to `reports/latest.md`.

## Dashboard

The dashboard includes:

- Current Bayesian market thesis and regime probabilities.
- Trade posture, entry trigger, invalidation, and risk note.
- Regulatory context, including configured SEC/CFTC digital commodity classification events.
- One chart for each configured crypto asset plus any open holdings from the ledger.
- Five days of hourly crypto data for tracked-asset charts and posture scoring.
- Top currency movers from Coinbase USD markets.
- Top 10 traded Coinbase USD markets, excluding assets already in the portfolio ledger or configured tracked assets when the ledger is empty.
- SQLite-backed data store status, including candle counts and stored date range.
- Initial capital tracking.
- ROI goal tracking with target days, required daily return, target equity, and remaining profit.
- Goal-aware trade candidates ranked from positive momentum and liquidity in the top mover/top traded universe.
- Transaction ledger for buys and sells.
- Open positions, cash, total equity, realized/unrealized P/L, total P/L, and ROI.

Market data and analysis runs are stored in `market_pulse.db`. Crypto candles are pruned to the configured five-day analysis window. Macro candles are retained longer because the macro model uses a three-month context window.

Ledger data is stored in `ledger.json`.

Example goal:

- Initial capital: `$1,000`
- Target ROI: `300%`
- Target window: `30 days`
- Target equity: `$4,000`
- Required compounded daily return: about `4.73%`

## Data Sources

Defaults:

- Crypto candles: Coinbase Exchange public API.
- Macro proxies: Yahoo Finance chart endpoint.

No API key is required for the default setup. If a data source is temporarily unavailable, the app records the error in the report and continues with available evidence.

## Configuration

Edit `config.json` to change:

- Crypto assets.
- Macro proxy symbols.
- Bayesian regime priors.
- Regulatory context events and affected assets.
- Report directory.
- Local timezone.
- SQLite path and retention window with `database_path` and `database_retention_days`.

## Important Boundary

This app is analytical decision support, not financial advice. It produces probabilities, confidence levels, invalidation conditions, and risk framing. The human user remains responsible for all market decisions.
