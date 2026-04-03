# papertrade

Standalone forward paper trade runtime for the `hybrid_aggressive_safe_valid` strategy.

## Current Architecture

- live market data comes from direct Bybit/Bitget REST calls
- Bybit liquidation completeness comes from the Python websocket/cache
- one SQLite file is the source-of-truth for:
  - `instruments`
  - `funding`
  - `open_interest`
  - `funding_round_snapshots`
  - `paper_runs`
  - `feature_snapshots`
  - `paper_positions`
  - `paper_position_rounds`
  - `paper_trades`
  - `paper_reports`
- model artifacts are bundled in `artifacts/risky.json` and `artifacts/safe.json`
- slippage uses `top_of_book` by default, with fixed-bps fallback

The default standalone deployment path does not require PostgreSQL.

## Package Layout

- trading logic: [src/papertrade/trading_logic](/d:/git/papertrade/src/papertrade/trading_logic)
- data streaming: [src/papertrade/data_streaming](/d:/git/papertrade/src/papertrade/data_streaming)
- execution: [src/papertrade/execution](/d:/git/papertrade/src/papertrade/execution)
- data management: [src/papertrade/data_management](/d:/git/papertrade/src/papertrade/data_management)

Compatibility shims still exist at the old `src/papertrade/*.py` paths so existing imports keep working during the transition.

## Main Files

- config: [src/papertrade/data_management/config.py](/d:/git/papertrade/src/papertrade/data_management/config.py)
- CLI: [src/papertrade/cli.py](/d:/git/papertrade/src/papertrade/cli.py)
- live runner: [src/papertrade/execution/continuous_runtime.py](/d:/git/papertrade/src/papertrade/execution/continuous_runtime.py)
- cycle runtime: [src/papertrade/execution/single_cycle_runtime.py](/d:/git/papertrade/src/papertrade/execution/single_cycle_runtime.py)
- snapshot collector: [src/papertrade/data_streaming/snapshot_collector.py](/d:/git/papertrade/src/papertrade/data_streaming/snapshot_collector.py)
- SQLite market/history store: [src/papertrade/data_streaming/sources/platform_db.py](/d:/git/papertrade/src/papertrade/data_streaming/sources/platform_db.py)
- SQLite snapshot store: [src/papertrade/data_streaming/sources/platform_snapshots.py](/d:/git/papertrade/src/papertrade/data_streaming/sources/platform_snapshots.py)
- state store: [src/papertrade/data_management/state_store.py](/d:/git/papertrade/src/papertrade/data_management/state_store.py)

## Environment

See [.env.example](/d:/git/papertrade/.env.example).

Important env vars for standalone live mode:

- `PAPERTRADE_RISKY_ARTIFACT_PATH=artifacts\\risky.json`
- `PAPERTRADE_SAFE_ARTIFACT_PATH=artifacts\\safe.json`
- `PAPERTRADE_PLATFORM_DB_PATH=data\\papertrade.sqlite3`
- `PAPERTRADE_STATE_DB_PATH=data\\papertrade.sqlite3`
- `PAPERTRADE_BYBIT_TAKER_FEE_BPS=6`
- `PAPERTRADE_BITGET_TAKER_FEE_BPS=6`
- `PAPERTRADE_LIVE_PLATFORM_SOURCES=true`
- `PAPERTRADE_LIVE_LIQUIDATION_SOURCE=true`
- `PAPERTRADE_LIVE_LIQUIDATION_CACHE_PATH=data\\liquidation-cache.json`
- `PAPERTRADE_SLIPPAGE_MODEL=top_of_book`

If `PAPERTRADE_STATE_DB_PATH` is omitted and `PAPERTRADE_PLATFORM_DB_PATH` is set, the runtime reuses the same SQLite file automatically.

## CLI

Entrypoint:

```powershell
python -m papertrade.cli run-forward
```

Useful args:

- `--pair BTC/USDT`
- `--continuous`
- `--max-cycles 3`
- `--poll-seconds 30`
- `--platform-db data\papertrade.sqlite3`
- `--state-db data\papertrade.sqlite3`
- `--resume-latest`
- `--resume-run-id <run_id>`

## Run Examples

Preflight only:

```powershell
python -m papertrade.cli run-forward
```

Standalone SQLite live run:

```powershell
$env:PAPERTRADE_RISKY_ARTIFACT_PATH="artifacts\\risky.json"
$env:PAPERTRADE_SAFE_ARTIFACT_PATH="artifacts\\safe.json"
$env:PAPERTRADE_PLATFORM_DB_PATH="data\\papertrade.sqlite3"
$env:PAPERTRADE_STATE_DB_PATH="data\\papertrade.sqlite3"
$env:PAPERTRADE_BYBIT_TAKER_FEE_BPS="6"
$env:PAPERTRADE_BITGET_TAKER_FEE_BPS="6"
$env:PAPERTRADE_LIVE_PLATFORM_SOURCES="true"
$env:PAPERTRADE_LIVE_LIQUIDATION_SOURCE="true"
$env:PAPERTRADE_LIVE_LIQUIDATION_CACHE_PATH="data\\liquidation-cache.json"
python -m papertrade.cli run-forward --continuous --poll-seconds 30 --report-dir reports
```

Resume latest interrupted run:

```powershell
$env:PAPERTRADE_RISKY_ARTIFACT_PATH="artifacts\\risky.json"
$env:PAPERTRADE_SAFE_ARTIFACT_PATH="artifacts\\safe.json"
$env:PAPERTRADE_PLATFORM_DB_PATH="data\\papertrade.sqlite3"
$env:PAPERTRADE_STATE_DB_PATH="data\\papertrade.sqlite3"
$env:PAPERTRADE_BYBIT_TAKER_FEE_BPS="6"
$env:PAPERTRADE_BITGET_TAKER_FEE_BPS="6"
$env:PAPERTRADE_LIVE_PLATFORM_SOURCES="true"
$env:PAPERTRADE_LIVE_LIQUIDATION_SOURCE="true"
$env:PAPERTRADE_LIVE_LIQUIDATION_CACHE_PATH="data\\liquidation-cache.json"
python -m papertrade.cli run-forward --continuous --poll-seconds 30 --resume-latest --report-dir reports
```

Fixture-backed single cycle:

```powershell
$env:PAPERTRADE_RISKY_ARTIFACT_PATH="artifacts\\risky.json"
$env:PAPERTRADE_SAFE_ARTIFACT_PATH="artifacts\\safe.json"
python -m papertrade.cli run-forward --input-file fixtures\\cycle.json --report-dir reports
```

Local SQLite plus JSON replay:

```powershell
$env:PAPERTRADE_RISKY_ARTIFACT_PATH="artifacts\\risky.json"
$env:PAPERTRADE_SAFE_ARTIFACT_PATH="artifacts\\safe.json"
$env:PAPERTRADE_PLATFORM_DB_PATH="data\\platform.sqlite3"
$env:PAPERTRADE_MARKET_STATE_SNAPSHOT_PATH="data\\market_states.json"
$env:PAPERTRADE_ORDERBOOK_SNAPSHOT_PATH="data\\orderbooks.json"
$env:PAPERTRADE_LIQUIDATION_EVENTS_PATH="data\\liquidations.json"
python -m papertrade.cli run-forward --pair BTC/USDT --now-utc 2025-01-11T07:59:00+00:00 --report-dir reports
```

## Docker

`docker-compose.yml` is configured for standalone SQLite live mode. It writes market data, snapshots, state, and liquidation cache into `/app/data/papertrade.sqlite3`.

Run:

```bash
docker compose up --build
```

## Outputs

- `reports/*.md`
- `reports/runs/*.json`
- `reports/trades/*.csv`
- `reports/cycles/*.json`

Cost model:

- `bybit_taker_fee_bps` and `bitget_taker_fee_bps` are configured separately
- trade-level `fee_bps` is the aggregated roundtrip cost for both legs: `2 * (bybit_taker_fee_bps + bitget_taker_fee_bps)`
- `slippage_model=top_of_book` estimates entry/exit slippage from top-of-book snapshots, with fixed-bps fallback

Trade log column meanings:

- `gross_bps` = funding 3 rounds combined
- `round1_gross_bps`, `round2_gross_bps`, `round3_gross_bps` = realized funding spread per round in bps
- `round1_gross_pnl`, `round2_gross_pnl`, `round3_gross_pnl` = realized funding amount per round on the trade notional
- `bybit_fee_bps` = Bybit taker fee roundtrip cost
- `bitget_fee_bps` = Bitget taker fee roundtrip cost
- `fee_bps` = total fee cost across both exchanges
- `slippage_bps` = slippage model estimate
- `net_bps` = `gross_bps - fee_bps - slippage_bps`

## Verification

```powershell
D:\git\papertrade\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Current result: `86` tests passing.

## Remaining Gaps

- no automated end-to-end test against real exchange endpoints
- liquidation completeness still depends on the Python websocket/cache, not exchange historical backfill
- direct exchange REST remains the live market source, so rate-limit behavior still matters in long-running deployments
