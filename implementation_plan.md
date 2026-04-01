# Implementation Checklist: Forward Paper Trade ใน `D:\git\papertrade`

อัปเดตล่าสุด: `2026-04-01`

เอกสารนี้ตั้งใจให้สะท้อนสถานะจริงของ repo ปัจจุบัน ไม่ใช่แผนในอุดมคติ
ติ๊ก `[x]` เฉพาะสิ่งที่มี implementation อยู่แล้วในโค้ดชุดนี้

## 1. สรุปสถานะปัจจุบัน

- [x] package entrypoint ชี้ `papertrade.cli:main`
- [x] รัน `python -m unittest discover -s tests -v` ผ่าน
- [x] ชุดทดสอบปัจจุบันผ่าน `62 tests`
- [x] รัน `python -m papertrade.cli run-forward` ได้
- [x] path default ของ CLI ยังเป็น preflight-only และ block ด้วย `missing_liquidation_source` ได้ถูกต้อง
- [x] รัน single-cycle runtime ได้ผ่าน `python -m papertrade.cli run-forward --input-file <fixture.json>`
- [x] รัน single-cycle runtime ได้ผ่าน `python -m papertrade.cli run-forward --pair BTC/USDT` เมื่อ config real sources ครบ
- [x] single-cycle runtime เขียน summary, run metadata, trade log, และ cycle artifact ลง disk ได้
- [x] รัน continuous runtime ได้ผ่าน `python -m papertrade.cli run-forward --pair BTC/USDT --continuous`
- [x] รัน continuous multi-pair runtime ได้ผ่าน `python -m papertrade.cli run-forward --continuous`
- [ ] exact forward run กับ source จริงยังไม่พร้อมใช้งาน

## 2. เป้าหมายของโปรเจกต์

- [x] จำลอง `forward paper trade` โดยไม่ส่ง order จริง
- [x] ใช้ funding cadence `8h`
- [x] ใช้ exit rule แบบถือครบ `3 funding rounds`
- [x] มี cost model ขั้นต้นผ่าน `fee_bps` และ `slippage_bps`
- [x] สร้าง markdown report และ CSV/JSON artifacts ขั้นต้นได้
- [ ] ทำงานกับ platform/live data source จริงได้
- [ ] ใช้ full-precision model artifacts จาก research จริงได้
- [ ] สร้าง equity curve / analytics output ที่ครบกว่านี้ได้

## 3. Decisions ที่ล็อกไว้ตอนนี้

- [x] source mode หลักของ repo นี้คือ `platform_forward`
- [x] runtime mode หลักคือ `forward_market_listener`
- [x] ใช้ `Decimal` ใน core path ที่เกี่ยวกับราคา, bps, score, และ PnL
- [x] canonical pair identity คือ `(base, quote)` และ `symbol = base + quote`
- [x] canonical round คือ `00:00Z`, `08:00Z`, `16:00Z`
- [x] decision cutoff คือ `funding_round - 30 seconds`
- [x] report filename ต้อง render `{as_of_round}` เป็น `YYYYMMDDTHHMMSSZ`
- [x] ถ้าไม่มี liquidation source แล้ว `strict_liquidation = true` ต้อง mark run เป็น `blocked`
- [x] threshold ของ scoring/rules ต้องมาจาก model artifact ได้

## 4. Tech Stack ที่ใช้อยู่จริง

- [x] ใช้ Python stdlib config loader แทน `pydantic-settings`
- [x] ใช้ `argparse` แทน `typer`
- [x] ใช้ `unittest` เป็น test runner หลัก
- [x] ใช้ `dataclass` + `Decimal` สำหรับ domain model
- [ ] เพิ่ม dependency สำหรับ DB integration จริง เช่น `sqlalchemy` / `psycopg`
- [ ] migrate ไปใช้ `pydantic-settings`
- [ ] migrate ไปใช้ `typer`
- [ ] migrate ไปใช้ `pytest`

## 5. Bootstrap / Packaging

- [x] มี [pyproject.toml](/d:/git/papertrade/pyproject.toml)
- [x] มี [README.md](/d:/git/papertrade/README.md)
- [x] มี [.env.example](/d:/git/papertrade/.env.example)
- [x] มี [.gitignore](/d:/git/papertrade/.gitignore)
- [x] package layout ใต้ [src/papertrade](/d:/git/papertrade/src/papertrade) พร้อมใช้งาน
- [x] test layout ใต้ [tests](/d:/git/papertrade/tests) พร้อมใช้งาน
- [x] packaging entrypoint ใน [pyproject.toml](/d:/git/papertrade/pyproject.toml) ตรงกับ CLI ปัจจุบัน

## 6. Domain Contracts

### 6.1 Pair / Instrument / Market Data

- [x] มี `Pair`
- [x] มี `Instrument`
- [x] มี `Level`
- [x] มี `Orderbook`
- [x] มี `MarketState`
- [x] มี `Funding`
- [x] มี `OpenInterest`
- [x] มี test สำหรับ pair filtering ที่ใช้ `funding_interval = 8`
- [x] มี logic list/load universe ขั้นต้นใน in-memory platform DB adapter
- [ ] enforce UTC normalization ใน real source adapters

### 6.2 Paper Trading Domain

- [x] มี `FundingRoundSnapshot`
- [x] มี `FeatureSnapshot`
- [x] มี `EntryDecision`
- [x] มี `PaperPositionRound`
- [x] มี `PaperPosition`
- [x] มี `PaperTrade`
- [x] มี `PaperRun`
- [x] enforce invariant ว่า closed position ต้องมี `close_reason`

## 7. Core Runtime Modules

### 7.1 Scheduler

- [x] มี [scheduler.py](/d:/git/papertrade/src/papertrade/scheduler.py)
- [x] คำนวณ next funding round ได้
- [x] คำนวณ decision cutoff ได้
- [x] คำนวณ exit round แบบ `T + 16h` ได้
- [ ] รองรับ backfill / replay mode

### 7.2 Feature Builder + Snapshot Collection

- [x] มี [feature_store.py](/d:/git/papertrade/src/papertrade/feature_store.py)
- [x] คำนวณ premium gap ได้
- [x] คำนวณ oi gap / oi total ได้
- [x] คำนวณ book imbalance abs gap ได้
- [x] คำนวณ signed spread ได้
- [x] mark `missing_lag_history` ได้
- [x] มี [snapshot_collector.py](/d:/git/papertrade/src/papertrade/snapshot_collector.py)
- [x] collector ดึง pair snapshots จาก bridge ได้
- [x] collector เช็ก stale / after-cutoff / empty orderbook ได้
- [x] collector คำนวณ liquidation window จาก liquidation adapter ได้
- [x] collector ดึง snapshot จาก file-backed source ได้
- [ ] ดึง snapshot จาก live bridge/source จริง

### 7.3 History Loader

- [x] มี [history.py](/d:/git/papertrade/src/papertrade/history.py)
- [x] โหลด funding history จาก platform DB adapter ได้
- [x] คำนวณ `lag1_abs_spread_bps` ได้
- [x] คำนวณ `rolling3_mean_abs_spread_bps` ได้
- [x] integrate history loader เข้ากับ orchestrator แล้ว
- [ ] โหลด historical features จาก DB/source จริง

### 7.4 Score Engine

- [x] มี [scoring.py](/d:/git/papertrade/src/papertrade/scoring.py)
- [x] มี generic `LogisticArtifact`
- [x] มี `compute_scores(...)`
- [x] รองรับ loading artifact จาก dict/json
- [x] threshold มาจาก artifact ได้
- [ ] ใส่ full-precision risky artifact จริง
- [ ] ใส่ full-precision safe artifact จริง
- [ ] เพิ่ม acceptance test กับ research vector จริง

### 7.5 Rule Evaluator

- [x] มี [rules.py](/d:/git/papertrade/src/papertrade/rules.py)
- [x] encode threshold ของ safe/risky ได้
- [x] มี direction rule `spread >= 0 -> short bybit / long bitget`
- [x] มี reason code `selected`
- [x] มี reason code `position_already_open`
- [x] มี reason code `below_safe_threshold`
- [x] มี reason code `below_risky_threshold`
- [x] มี reason code `below_both_threshold`
- [ ] reason code ยังไม่ละเอียดสำหรับ invalid source/data ทุกกรณี

### 7.6 Orchestrator

- [x] มี [orchestrator.py](/d:/git/papertrade/src/papertrade/orchestrator.py)
- [x] มี single-cycle evaluate flow
- [x] validate pair / exchange / round / cutoff contract ของ snapshots
- [x] skip scoring เมื่อ `entry_evaluable = False`
- [x] resolve lag/rolling history จาก platform DB adapter ได้
- [x] มี continuous funding loop สำหรับหลาย pair

### 7.7 Portfolio Simulator

- [x] มี [portfolio.py](/d:/git/papertrade/src/papertrade/portfolio.py)
- [x] เปิด position ได้
- [x] settle funding ต่อรอบได้
- [x] ปิด position หลังครบ 3 rounds ได้
- [x] คำนวณ gross/net bps และ pnl ได้
- [x] mark `settlement_error` ได้เมื่อ funding ขาด
- [x] กัน settlement ก่อน entry / ซ้ำ / ย้อนเวลา / เกิน planned exit ได้
- [x] update `max_drawdown_pct` ใน completed close path ได้
- [ ] เพิ่ม portfolio constraints เช่น max concurrent positions
- [ ] เพิ่ม re-entry cooldown policy

### 7.8 Report / Persistence

- [x] มี [report.py](/d:/git/papertrade/src/papertrade/report.py)
- [x] render filename แบบ Windows-safe ได้
- [x] เขียน markdown summary ลง disk จริงได้
- [x] มี [persistence.py](/d:/git/papertrade/src/papertrade/persistence.py)
- [x] เขียน run metadata เป็น JSON ได้
- [x] เขียน trade log เป็น CSV ได้
- [x] เขียน cycle artifact เป็น JSON ได้
- [ ] เขียน Parquet trade log
- [ ] เก็บ metadata ลง SQLite / DuckDB / Postgres

### 7.9 Config / Runtime / CLI

- [x] มี [config.py](/d:/git/papertrade/src/papertrade/config.py)
- [x] load config จาก env ได้
- [x] validate config ขั้นพื้นฐานได้
- [x] มี [runtime.py](/d:/git/papertrade/src/papertrade/runtime.py) สำหรับ preflight status
- [x] มี [cli.py](/d:/git/papertrade/src/papertrade/cli.py)
- [x] มี command `python -m papertrade.cli run-forward`
- [x] CLI return blocked เมื่อขาด liquidation source
- [x] มี runtime path สำหรับ `failed` หลัง preflight ผ่านแล้ว
- [x] มี [single_cycle_runtime.py](/d:/git/papertrade/src/papertrade/single_cycle_runtime.py)
- [x] CLI รองรับ `--input-file` สำหรับ single-cycle runtime จาก fixture
- [x] CLI รองรับ `--continuous`, `--max-cycles`, และ `--poll-seconds`
- [ ] CLI args ยังไม่ครบตามแผนเดิม เช่น initial-equity / fee-bps / slippage-bps override
- [ ] full runtime loop ตาม funding rounds จริงยังไม่รองรับ live transport จริง

## 8. Source Adapters

### 8.1 Platform DB Adapter

- [x] มี protocol ใน [platform_db.py](/d:/git/papertrade/src/papertrade/sources/platform_db.py)
- [x] มี `InMemoryPlatformDBSource`
- [x] load `funding` history แบบ filter ตาม pair/exchange ได้
- [x] load `open_interest` history แบบ filter ตาม pair/exchange ได้
- [x] implement pair filtering จาก `instruments` แบบ in-memory ได้
- [x] มี `SQLitePlatformDBSource` สำหรับ query history/instruments จาก SQLite จริง
- [ ] implement external DB adapter สำหรับ production source จริง

### 8.2 Platform Bridge Adapter

- [x] มี [platform_bridge.py](/d:/git/papertrade/src/papertrade/sources/platform_bridge.py)
- [x] เก็บ latest market state ได้
- [x] เก็บ latest orderbook ได้
- [x] มี `FilePlatformBridge` สำหรับอ่าน latest snapshots จาก JSON files
- [ ] เชื่อม bridge กับ platform/live transport จริง

### 8.3 Liquidation Adapter

- [x] มี protocol ใน [liquidation.py](/d:/git/papertrade/src/papertrade/sources/liquidation.py)
- [x] มี `InMemoryLiquidationSource`
- [x] sum liquidation USD ตามช่วงเวลาได้
- [x] มี `JsonFileLiquidationSource` สำหรับอ่าน liquidation events จาก JSON file
- [ ] implement source production จริงของ `bybit_liquidation_amount_8h`
- [ ] ทำให้ preflight รู้ availability จาก source จริง แทน fixture override

## 9. Runtime Path ที่มีอยู่จริง

### 9.1 Preflight-Only Path

- [x] `python -m papertrade.cli run-forward`
- [x] สร้าง `PaperRun`
- [x] เช็ก availability ของ artifacts
- [x] block เมื่อ strict liquidation เปิดแต่ไม่มี source

### 9.2 Fixture-Backed Single-Cycle Path

- [x] `python -m papertrade.cli run-forward --input-file <fixture.json>`
- [x] load snapshots/history/liquidation events จาก JSON fixture ได้
- [x] collect snapshots ผ่าน `SnapshotCollector`
- [x] evaluate feature/score/decision ผ่าน `SingleCycleOrchestrator`
- [x] เปิด position ได้ถ้า decision selected
- [x] mark run เป็น `finished` ได้
- [x] เขียน summary / runs / trades / cycles artifacts ได้
- [ ] settle funding รอบถัดไปต่อเนื่องอัตโนมัติ
- [ ] รันหลาย pair ในรอบเดียว

### 9.3 SQLite/JSON-Backed Single-Cycle Path

- [x] `python -m papertrade.cli run-forward --pair BTC/USDT --now-utc ...`
- [x] load funding/open-interest history จาก SQLite source ได้
- [x] load latest market state / orderbook จาก JSON source files ได้
- [x] load liquidation events จาก JSON source file ได้
- [x] preflight block เมื่อ platform DB หรือ bridge source paths ยังไม่พร้อมได้
- [ ] ยังไม่ต่อกับ live platform transport จริง

## 10. Tests

- [x] มี [test_cli.py](/d:/git/papertrade/tests/test_cli.py)
- [x] มี [test_history.py](/d:/git/papertrade/tests/test_history.py)
- [x] มี [test_orchestrator.py](/d:/git/papertrade/tests/test_orchestrator.py)
- [x] มี [test_persistence.py](/d:/git/papertrade/tests/test_persistence.py)
- [x] มี [test_portfolio.py](/d:/git/papertrade/tests/test_portfolio.py)
- [x] มี [test_report_naming.py](/d:/git/papertrade/tests/test_report_naming.py)
- [x] มี [test_rules.py](/d:/git/papertrade/tests/test_rules.py)
- [x] มี [test_runtime.py](/d:/git/papertrade/tests/test_runtime.py)
- [x] มี [test_scheduler.py](/d:/git/papertrade/tests/test_scheduler.py)
- [x] มี [test_scoring.py](/d:/git/papertrade/tests/test_scoring.py)
- [x] มี [test_single_cycle_runtime.py](/d:/git/papertrade/tests/test_single_cycle_runtime.py)
- [x] มี [test_snapshot_collector.py](/d:/git/papertrade/tests/test_snapshot_collector.py)
- [x] มี [test_source_adapters.py](/d:/git/papertrade/tests/test_source_adapters.py)
- [x] มี [test_real_source_adapters.py](/d:/git/papertrade/tests/test_real_source_adapters.py)
- [x] pair filtering test ผ่าน
- [x] lag funding features test ผ่าน
- [x] single-cycle runtime integration test ผ่าน
- [x] continuous runtime integration test ผ่าน
- [x] continuous multi-pair CLI integration test ผ่าน
- [x] SQLite/JSON-backed CLI integration test ผ่าน
- [ ] research acceptance vector test
- [ ] integration test กับ source จริง
- [ ] failed writer / persistence error path test

## 11. Phase Checklist

### Phase 0: Bootstrap Repo

- [x] สร้าง `pyproject.toml`
- [x] สร้าง package layout
- [x] สร้าง test layout
- [x] ตั้ง baseline test ให้รันได้จริง

### Phase 1: Contracts + Config + CLI Skeleton

- [x] เขียน domain dataclasses
- [x] เขียน config loader
- [x] เขียน CLI skeleton
- [x] เขียน preflight blocked semantics ขั้นต้น

### Phase 2: In-Memory Adapters

- [x] นิยาม DB adapter protocol
- [x] นิยาม bridge adapter
- [x] นิยาม liquidation protocol
- [x] implement in-memory platform DB adapter
- [x] implement in-memory bridge
- [x] implement in-memory liquidation source
- [x] implement SQLite/file-backed adapters สำหรับ local real resources
- [ ] implement external DB / bridge / liquidation adapters สำหรับ production source จริง

### Phase 3: Scheduler + Feature + Snapshot + History

- [x] เขียน funding round scheduler
- [x] เขียน feature builder
- [x] เขียน snapshot collector
- [x] เขียน history loader จาก funding history
- [ ] เชื่อมกับ source จริง

### Phase 4: Scoring + Rules + Orchestrator

- [x] มี generic logistic scoring engine
- [x] มี rule evaluator
- [x] มี single-cycle orchestrator
- [x] ใช้ threshold จาก artifact ได้
- [ ] โหลด research artifacts จริง
- [ ] เทียบ score กับ acceptance vector จริง

### Phase 5: Persistence + Single-Cycle Runtime

- [x] เขียน markdown summary output จริง
- [x] เขียน CSV trade log จริง
- [x] เขียน JSON run/cycle artifacts จริง
- [x] wire CLI -> collector -> orchestrator -> persistence สำหรับ single cycle
- [x] wire CLI -> SQLite/JSON sources -> collector -> orchestrator -> persistence สำหรับ single cycle
- [x] ขยายเป็น multi-pair continuous runtime

### Phase 6: Hardening

- [x] มี blocked semantics
- [x] มี failed semantics ใน CLI runtime path
- [x] มี invariant checks และ settlement guards
- [ ] เพิ่ม replay / live integration tests
- [ ] เพิ่ม persistence error handling tests

## 12. Blockers สำหรับ Exact Forward Hybrid

- [ ] platform ต้อง expose live `MarketState`
- [ ] platform ต้อง expose live `Orderbook`
- [ ] ต้องมี liquidation source จริงสำหรับ `bybit_liquidation_amount_8h`
- [ ] ต้องมี full-precision risky artifact
- [ ] ต้องมี full-precision safe artifact
- [ ] ต้องมี runtime loop ที่ถือ position ผ่าน 3 funding rounds จาก source จริง

ตราบใดที่ blocker เหล่านี้ยังไม่ปิด:

- [x] repo นี้ยังพัฒนา scheduler / scoring / rules / portfolio / report pipeline ต่อได้
- [x] CLI ยัง block exact run ได้อย่างถูกต้อง
- [x] fixture-backed single-cycle run ใช้เป็น integration scaffold ได้
- [ ] exact forward run ของ `hybrid_aggressive_safe_valid` ยังไม่ถือว่า production-ready

## 13. Definition Of Done สำหรับ Phase แรก

- [x] repo มี runnable core modules
- [x] repo มี CLI path ที่รันได้จริงอย่างน้อยหนึ่งแบบ
- [x] repo มี unittest suite และรันผ่าน
- [x] repo มี blocked / failed / finished semantics สำหรับ path ปัจจุบัน
- [x] เขียน markdown + csv + json artifacts ได้จริง
- [x] ใช้ artifact thresholds ใน scoring/rules ได้จริง
- [ ] load universe จาก instruments/DB จริงได้
- [ ] รับ live-compatible `MarketState` และ `Orderbook` จาก platform จริงได้
- [ ] คำนวณ score จาก full-precision research artifacts จริงได้
- [ ] ผ่าน acceptance vector จาก research
- [ ] เปิด/ปิด position ตาม 3 funding rounds ด้วย source จริงได้

## 14. งานถัดไปที่ควรทำ

- [ ] เพิ่ม sample fixture + อัปเดต README ให้รัน single-cycle runtime ได้ทันที
- [ ] เพิ่ม sample SQLite/JSON source files สำหรับรัน real-source single cycle ได้ทันที
- [ ] implement external/live adapters สำหรับ platform DB / bridge / liquidation
- [ ] ทำ runtime availability ให้ตรวจ source จริง ไม่ใช่ fixture override
- [x] ขยาย single-cycle runtime เป็น multi-pair / multi-cycle loop
- [ ] export full-precision model artifacts จาก research repo
- [ ] เพิ่ม research acceptance vector test
- [ ] เพิ่ม Parquet / DB persistence ถ้าจะใช้วิเคราะห์ผลย้อนหลัง
