# Implementation Checklist: Forward Paper Trade

Updated: `2026-04-03`

This checklist reflects the current state of `D:\git\papertrade` after switching the live path to standalone SQLite.

## 0. Architecture Split

- [x] Split code into `trading_logic`, `data_streaming`, `execution`, and `data_management`
- [x] Update internal imports, tests, and docs to use the new package layout
- [x] Remove legacy `src/papertrade/*.py` and `src/papertrade/sources/*.py` shim modules

## 1. Scope

- [x] Use entry rule `safe_score >= 0.151704` and `risky_score >= 0.2071180075`
- [x] Use exit rule `hold 3 funding rounds`
- [x] Paper trade only, no real order submission
- [x] Persist trade log, PnL, fee, and slippage
- [x] Support separate taker fee config for Bybit and Bitget
- [x] Support continuous forward run across multiple pairs
- [x] Support restart and recovery of open positions

## 2. Source Of Truth

- [x] Standalone live path uses one SQLite file as the main runtime store
- [x] SQLite stores `instruments`, `funding`, `open_interest`, and `funding_round_snapshots`
- [x] SQLite also stores `paper_runs`, `feature_snapshots`, `paper_positions`, `paper_position_rounds`, `paper_trades`, and `paper_reports`
- [x] Live market data comes from direct Bybit/Bitget REST via Python adapters
- [x] Bybit liquidation completeness comes from Python websocket/cache
- [ ] Liquidation source is still not canonicalized into one exchange-independent source

## 3. Data Contracts

- [x] `Instrument`
- [x] `MarketState`
- [x] `Orderbook`
- [x] `Funding`
- [x] `OpenInterest`
- [x] `FundingRoundSnapshot`
- [x] `FeatureSnapshot`
- [x] `PaperRun`
- [x] `PaperPosition`
- [x] `PaperPositionRound`
- [x] `PaperTrade`

## 4. Adapters

- [x] `ExchangeRestPlatformBridge`
- [x] `ExchangeRestPlatformDBSource`
- [x] `SQLitePlatformDBSource`
- [x] `SQLiteFundingRoundSnapshotSource`
- [x] `FilePlatformBridge`
- [x] `JsonFileLiquidationSource`
- [x] SQLite market store can upsert instruments
- [x] SQLite market store can upsert funding history
- [x] SQLite market store can upsert open-interest history
- [x] SQLite snapshot store can upsert `funding_round_snapshots`

## 5. Runtime

- [x] Single-cycle runtime
- [x] Continuous runtime
- [x] Multi-pair continuous loop
- [x] Standalone live mode uses REST bridge plus SQLite market store
- [x] Live cycles persist fresh funding-round snapshots into SQLite
- [x] Strict liquidation preflight
- [x] Runtime availability can detect `standalone_sqlite_live`

## 6. Persistence And Recovery

- [x] SQLite state store
- [x] Reuse `platform_db_path` as `state_db_path` automatically when `state_db_path` is omitted
- [x] Persist `paper_runs`
- [x] Persist `feature_snapshots`
- [x] Persist `paper_positions`
- [x] Persist `paper_position_rounds`
- [x] Persist `paper_trades`
- [x] Persist `paper_reports`
- [x] Resume latest run
- [x] Resume by `run_id`
- [x] Recover open positions after restart
- [x] Enforce closed-position `close_reason` invariant
- [x] Enable SQLite `WAL` mode for runtime/state tables

## 7. Research Parity

- [x] Real risky artifact in [artifacts/risky.json](/d:/git/papertrade/artifacts/risky.json)
- [x] Real safe artifact in [artifacts/safe.json](/d:/git/papertrade/artifacts/safe.json)
- [x] Acceptance test for mean-point score
- [x] Acceptance test for selected high-conviction vector
- [x] Rule thresholds can be read from artifacts

## 8. CLI

- [x] `papertrade.cli:main`
- [x] `run-forward`
- [x] `--pair`
- [x] `--continuous`
- [x] `--max-cycles`
- [x] `--poll-seconds`
- [x] `--platform-db`
- [x] `--state-db`
- [x] `--platform-postgres-dsn` still exists for backward compatibility
- [x] `--resume-latest`
- [x] `--resume-run-id`

## 9. Reporting

- [x] Markdown summary
- [x] JSON run metadata
- [x] JSON cycle artifacts
- [x] CSV trade log
- [x] Windows-safe filename rendering
- [x] Report records are written into the SQLite state store

## 10. Packaging

- [x] Docker image copies model artifacts into `/app/artifacts`
- [x] `docker-compose.yml` runs standalone SQLite live mode
- [x] Docker path writes all runtime state into `/app/data/papertrade.sqlite3`
- [x] Docker path does not require PostgreSQL

## 11. Tests

- [x] Scheduler
- [x] Scoring
- [x] Rules
- [x] Orchestrator
- [x] Snapshot collector
- [x] Portfolio lifecycle
- [x] CLI fixture/local modes
- [x] Continuous multi-cycle
- [x] Continuous recovery from state store
- [x] SQLite snapshot source
- [x] Runtime availability for `standalone_sqlite_live`
- [x] State store constraints

## 12. Remaining Gaps

- [ ] No automated end-to-end test against real exchange endpoints
- [ ] Liquidation completeness still depends on the Python websocket/cache
- [ ] REST rate-limit behavior still needs operational verification for long-running deployment
- [ ] Legacy PostgreSQL code paths still exist in the repo, even though the default live path no longer depends on them

## 13. Definition Of Done

- [x] Default live forward path is standalone SQLite
- [x] Runtime has durable state and recovery
- [x] Model artifacts match research formulas
- [x] Docker compose can run without PostgreSQL
- [x] Tests cover the main parity and recovery paths
- [ ] Live environment verification against real exchange endpoints still needs to be done
