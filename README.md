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
- live Bybit/Bitget REST source adapters
- single-cycle CLI runtime
- continuous multi-cycle CLI runtime
- multi-pair continuous loop from SQLite pair universe
- single-pair live REST runtime
- test suite

Not implemented yet:
- live liquidation integration
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

SQLite/JSON-backed continuous run:

Simulated multi-cycle run:

```powershell
$env:PAPERTRADE_RISKY_ARTIFACT_PATH="artifacts\\risky.json"
$env:PAPERTRADE_SAFE_ARTIFACT_PATH="artifacts\\safe.json"
$env:PAPERTRADE_PLATFORM_DB_PATH="data\\platform.sqlite3"
$env:PAPERTRADE_MARKET_STATE_SNAPSHOT_PATH="data\\market_states.json"
$env:PAPERTRADE_ORDERBOOK_SNAPSHOT_PATH="data\\orderbooks.json"
$env:PAPERTRADE_LIQUIDATION_EVENTS_PATH="data\\liquidations.json"
python -m papertrade.cli run-forward --pair BTC/USDT --continuous --now-utc 2025-01-11T07:59:00+00:00 --max-cycles 3 --poll-seconds 0 --report-dir reports
```

Real-time polling run:

```powershell
$env:PAPERTRADE_RISKY_ARTIFACT_PATH="artifacts\\risky.json"
$env:PAPERTRADE_SAFE_ARTIFACT_PATH="artifacts\\safe.json"
$env:PAPERTRADE_PLATFORM_DB_PATH="data\\platform.sqlite3"
$env:PAPERTRADE_MARKET_STATE_SNAPSHOT_PATH="data\\market_states.json"
$env:PAPERTRADE_ORDERBOOK_SNAPSHOT_PATH="data\\orderbooks.json"
$env:PAPERTRADE_LIQUIDATION_EVENTS_PATH="data\\liquidations.json"
python -m papertrade.cli run-forward --pair BTC/USDT --continuous --poll-seconds 30 --report-dir reports
```

All-pairs continuous run from SQLite universe:

```powershell
$env:PAPERTRADE_RISKY_ARTIFACT_PATH="artifacts\\risky.json"
$env:PAPERTRADE_SAFE_ARTIFACT_PATH="artifacts\\safe.json"
$env:PAPERTRADE_PLATFORM_DB_PATH="data\\platform.sqlite3"
$env:PAPERTRADE_MARKET_STATE_SNAPSHOT_PATH="data\\market_states.json"
$env:PAPERTRADE_ORDERBOOK_SNAPSHOT_PATH="data\\orderbooks.json"
$env:PAPERTRADE_LIQUIDATION_EVENTS_PATH="data\\liquidations.json"
python -m papertrade.cli run-forward --continuous --now-utc 2025-01-11T07:59:00+00:00 --max-cycles 3 --poll-seconds 0 --report-dir reports
```

Live REST-backed single cycle:

```powershell
$env:PAPERTRADE_RISKY_ARTIFACT_PATH="artifacts\\risky.json"
$env:PAPERTRADE_SAFE_ARTIFACT_PATH="artifacts\\safe.json"
$env:PAPERTRADE_LIVE_PLATFORM_SOURCES="true"
$env:PAPERTRADE_STRICT_LIQUIDATION="false"
python -m papertrade.cli run-forward --pair BTC/USDT --report-dir reports
```

Expected local-source files:
- `platform.sqlite3`
  - tables: `instruments`, `funding`, `open_interest`
- `market_states.json`
  - JSON array of market-state records with `exchange`, `base`, `quote`, `index_price`, `mark_price`, `funding_rate`, `open_interest`, `updated_at`
- `orderbooks.json`
  - JSON array of orderbook records with `exchange`, `base`, `quote`, `bids`, `asks`, `updated_at`
- `liquidations.json`
  - JSON array of liquidation events with `base`, `quote`, `time`, `usd_size`

Live REST source notes:
- market state and orderbook are fetched from public Bybit/Bitget REST endpoints at runtime
- funding and open-interest history are fetched from public Bybit/Bitget REST endpoints at runtime
- live liquidation is not implemented yet, so `PAPERTRADE_STRICT_LIQUIDATION=false` is required for live REST runs today

## Docker

Build image:

```powershell
docker build -t papertrade:local .
```

Run fixture-backed single cycle:

```powershell
docker run --rm `
  -v ${PWD}\reports:/app/reports `
  -v ${PWD}\fixtures:/app/fixtures:ro `
  -v ${PWD}\artifacts:/app/artifacts:ro `
  -e PAPERTRADE_RISKY_ARTIFACT_PATH=/app/artifacts/risky.json `
  -e PAPERTRADE_SAFE_ARTIFACT_PATH=/app/artifacts/safe.json `
  papertrade:local `
  run-forward `
  --input-file /app/fixtures/cycle.json `
  --report-dir /app/reports
```

Run SQLite/JSON-backed single cycle:

```powershell
docker run --rm `
  -v ${PWD}\reports:/app/reports `
  -v ${PWD}\data:/app/data:ro `
  -v ${PWD}\artifacts:/app/artifacts:ro `
  -e PAPERTRADE_RISKY_ARTIFACT_PATH=/app/artifacts/risky.json `
  -e PAPERTRADE_SAFE_ARTIFACT_PATH=/app/artifacts/safe.json `
  -e PAPERTRADE_PLATFORM_DB_PATH=/app/data/platform.sqlite3 `
  -e PAPERTRADE_MARKET_STATE_SNAPSHOT_PATH=/app/data/market_states.json `
  -e PAPERTRADE_ORDERBOOK_SNAPSHOT_PATH=/app/data/orderbooks.json `
  -e PAPERTRADE_LIQUIDATION_EVENTS_PATH=/app/data/liquidations.json `
  papertrade:local `
  run-forward `
  --pair BTC/USDT `
  --now-utc 2025-01-11T07:59:00+00:00 `
  --report-dir /app/reports
```

Output files are written to the host `reports` directory through the mounted volume:
- `runs/*.json`
- `trades/*.csv`
- `cycles/*.json`
- `*.md`
