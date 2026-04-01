# papertrade

Python scaffold for forward paper trading using platform-compatible contracts.

Current scope:
- domain contracts
- scheduler
- scoring engine
- rule evaluator
- portfolio simulator
- report and persistence pipeline
- in-memory adapters
- SQLite/JSON-backed source adapters
- single-cycle CLI runtime
- test suite

Not implemented yet:
- continuous multi-cycle runtime
- live transport integration
- full-precision research artifacts
- research acceptance tests

Run CLI:

Preflight only:

```powershell
python -m papertrade.cli run-forward
```

Fixture-backed single cycle:

```powershell
$env:PAPERTRADE_RISKY_ARTIFACT_PATH="artifacts\\risky.json"
$env:PAPERTRADE_SAFE_ARTIFACT_PATH="artifacts\\safe.json"
python -m papertrade.cli run-forward --input-file fixtures\\cycle.json --report-dir reports
```

SQLite/JSON-backed single cycle:

```powershell
$env:PAPERTRADE_RISKY_ARTIFACT_PATH="artifacts\\risky.json"
$env:PAPERTRADE_SAFE_ARTIFACT_PATH="artifacts\\safe.json"
$env:PAPERTRADE_PLATFORM_DB_PATH="data\\platform.sqlite3"
$env:PAPERTRADE_MARKET_STATE_SNAPSHOT_PATH="data\\market_states.json"
$env:PAPERTRADE_ORDERBOOK_SNAPSHOT_PATH="data\\orderbooks.json"
$env:PAPERTRADE_LIQUIDATION_EVENTS_PATH="data\\liquidations.json"
python -m papertrade.cli run-forward --pair BTC/USDT --now-utc 2025-01-11T07:59:00+00:00 --report-dir reports
```

Expected real-source files:
- `platform.sqlite3`
  - tables: `instruments`, `funding`, `open_interest`
- `market_states.json`
  - JSON array of market-state records with `exchange`, `base`, `quote`, `index_price`, `mark_price`, `funding_rate`, `open_interest`, `updated_at`
- `orderbooks.json`
  - JSON array of orderbook records with `exchange`, `base`, `quote`, `bids`, `asks`, `updated_at`
- `liquidations.json`
  - JSON array of liquidation events with `base`, `quote`, `time`, `usd_size`
