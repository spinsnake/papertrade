# Implementation Checklist: Forward Paper Trade ใน `D:\git\papertrade`

อัปเดตล่าสุด: `2026-04-01`

เอกสารนี้เปลี่ยนจาก plan แบบ narrative เป็น checklist ที่สะท้อนสถานะจริงของ repo ปัจจุบัน
ติ๊ก `[x]` เฉพาะสิ่งที่มี implementation อยู่แล้วใน repo นี้

## 1. เป้าหมายของโปรเจกต์

- [ ] ทำ `forward paper trade` สำหรับกลยุทธ์ `hybrid_aggressive_safe_valid`
- [ ] ใช้ entry rule: `safe_score >= 0.151704` และ `risky_score >= 0.2071180075`
- [ ] ใช้ exit rule: ถือจนรับ funding ครบ `3 funding rounds`
- [ ] ไม่ส่ง order จริง
- [ ] สร้าง trade log, equity curve, cost breakdown, และ markdown report ได้ครบ

## 2. สถานะที่ verify แล้ว

- [x] มี Python project scaffold ใน `D:\git\papertrade`
- [x] import โมดูลหลักทั้งหมดผ่าน
- [x] รัน `python -m unittest discover -s tests -v` ผ่าน
- [x] รัน `python -m papertrade.cli run-forward` ได้
- [x] CLI ตอนนี้ block ตาม preflight ด้วย `missing_liquidation_source`

## 3. Decisions ที่ล็อกไว้ตอนนี้

- [x] source mode หลักของ repo นี้คือ `platform_forward`
- [x] ใช้ `Decimal` ใน core path ที่เกี่ยวกับราคา, bps, และ PnL
- [x] canonical pair identity คือ `(base, quote)` และ `symbol = base + quote`
- [x] funding round ใช้ cadence `8h`
- [x] canonical round คือ `00:00Z`, `08:00Z`, `16:00Z`
- [x] decision cutoff คือ `funding_round - 30 seconds`
- [x] filename ของ report ต้อง render `{as_of_round}` เป็น `YYYYMMDDTHHMMSSZ`
- [x] ถ้าไม่มี liquidation source แล้ว `strict_liquidation = true` ต้อง mark run เป็น `blocked`

## 4. Tech Stack ที่ใช้อยู่จริงใน repo

- [x] ใช้ Python stdlib config loader แทน `pydantic-settings`
- [x] ใช้ `argparse` แทน `typer`
- [x] ใช้ `unittest` แทน `pytest` สำหรับ test ที่รันได้จริงตอนนี้
- [x] ใช้ `dataclass` + `Decimal` สำหรับ domain model
- [ ] migrate ไปใช้ `uv`
- [ ] migrate ไปใช้ `pydantic-settings`
- [ ] migrate ไปใช้ `typer`
- [ ] migrate ไปใช้ `pytest`
- [ ] เพิ่ม dependency ที่ต้องใช้จริงสำหรับ DB integration เช่น `sqlalchemy` / `psycopg`

## 5. Bootstrap Repo

- [x] สร้าง [pyproject.toml](/d:/git/papertrade/pyproject.toml)
- [x] สร้าง [README.md](/d:/git/papertrade/README.md)
- [x] สร้าง [.env.example](/d:/git/papertrade/.env.example)
- [x] สร้าง [.gitignore](/d:/git/papertrade/.gitignore)
- [x] สร้าง package layout ใต้ [src/papertrade](/d:/git/papertrade/src/papertrade)
- [x] สร้าง test layout ใต้ [tests](/d:/git/papertrade/tests)
- [ ] จัด packaging entrypoint ใน `pyproject.toml` ให้ตรงกับ CLI ปัจจุบัน

## 6. Canonical Data Contract

### 6.1 Instrument / Pair

- [x] มี `Pair`
- [x] มี `Instrument`
- [x] `Pair.symbol` คืนค่า `base + quote`
- [ ] เพิ่ม test สำหรับ pair filtering ที่ใช้ `funding_interval = 8`
- [ ] เพิ่ม logic load universe จาก `instruments` จริง

### 6.2 MarketState / Orderbook / Funding / OpenInterest

- [x] มี `MarketState`
- [x] มี `Orderbook`
- [x] มี `Level`
- [x] มี `Funding`
- [x] มี `OpenInterest`
- [ ] enforce UTC normalization ใน source adapters จริง
- [ ] โหลด historical `funding` จาก DB จริง
- [ ] โหลด historical `open_interest` จาก DB จริง

### 6.3 Paper Trade Domain Model

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
- [ ] รองรับ backfill/replay mode

### 7.2 Feature Builder

- [x] มี [feature_store.py](/d:/git/papertrade/src/papertrade/feature_store.py)
- [x] คำนวณ premium gap ได้
- [x] คำนวณ oi gap / oi total ได้
- [x] คำนวณ book imbalance abs gap ได้
- [x] คำนวณ signed spread ได้
- [x] mark `missing_lag_history` ได้
- [ ] สร้าง snapshot collector ที่ดึง data จาก source จริง
- [ ] เติม logic freshness / stale policy ให้ครบ
- [ ] เติม liquidation window logic จาก source จริง

### 7.3 Score Engine

- [x] มี [scoring.py](/d:/git/papertrade/src/papertrade/scoring.py)
- [x] มี generic `LogisticArtifact`
- [x] มี `compute_scores(...)`
- [x] รองรับ loading artifact จาก dict/json
- [ ] ใส่ full-precision risky artifact จริง
- [ ] ใส่ full-precision safe artifact จริง
- [ ] เพิ่ม acceptance test กับ research vector จริง
- [ ] ทำให้ threshold มาจาก artifact/strategy config โดยตรง

### 7.4 Rule Evaluator

- [x] มี [rules.py](/d:/git/papertrade/src/papertrade/rules.py)
- [x] encode threshold ของ safe/risky
- [x] มี direction rule: `spread >= 0 -> short bybit / long bitget`
- [x] มี reason code `selected`
- [x] มี reason code `position_already_open`
- [x] มี reason code `below_safe_threshold`
- [x] มี reason code `below_risky_threshold`
- [x] มี reason code `below_both_threshold`
- [ ] เพิ่ม reason code path สำหรับ missing market state / orderbook แยกละเอียดกว่านี้

### 7.5 Portfolio Simulator

- [x] มี [portfolio.py](/d:/git/papertrade/src/papertrade/portfolio.py)
- [x] เปิด position ได้
- [x] settle funding ต่อรอบได้
- [x] ปิด position หลังครบ 3 rounds ได้
- [x] คำนวณ gross/net bps ได้
- [x] คำนวณ gross/net pnl ได้
- [x] mark `settlement_error` ได้เมื่อ funding ขาด
- [ ] เพิ่ม drawdown calculation ให้ครบทุก branch
- [ ] เพิ่ม portfolio constraints เช่น max concurrent positions
- [ ] เพิ่ม re-entry cooldown policy

### 7.6 Report / Persistence

- [x] มี [report.py](/d:/git/papertrade/src/papertrade/report.py)
- [x] render filename แบบ Windows-safe ได้
- [x] มี summary renderer ขั้นต้น
- [x] มี [persistence.py](/d:/git/papertrade/src/papertrade/persistence.py) สำหรับ JSON artifact store แบบง่าย
- [ ] เขียน markdown report ลง disk จริง
- [ ] เขียน CSV trade log
- [ ] เขียน Parquet trade log
- [ ] เก็บ run metadata ลง SQLite / DuckDB / Postgres
- [ ] เก็บ funding round snapshots / feature snapshots / trades ลง persistence layer จริง

### 7.7 Config / Runtime / CLI

- [x] มี [config.py](/d:/git/papertrade/src/papertrade/config.py)
- [x] load config จาก env ได้
- [x] validate config ขั้นพื้นฐานได้
- [x] มี [runtime.py](/d:/git/papertrade/src/papertrade/runtime.py) สำหรับ preflight status
- [x] มี [cli.py](/d:/git/papertrade/src/papertrade/cli.py)
- [x] มี command `python -m papertrade.cli run-forward`
- [x] CLI return blocked เมื่อขาด liquidation source
- [ ] เพิ่ม CLI args ให้ครบตามแผนเดิม เช่น initial-equity / fee-bps / slippage-bps / source-mode override
- [ ] สร้าง orchestrator ที่รัน full loop จริงตาม funding round
- [ ] เพิ่ม runtime path สำหรับ `failed` หลัง preflight ผ่านแล้ว

## 8. Source Adapters

### 8.1 Platform DB Adapter

- [x] มี interface ใน [platform_db.py](/d:/git/papertrade/src/papertrade/sources/platform_db.py)
- [ ] implement query `instruments` จริง
- [ ] implement query `funding` history จริง
- [ ] implement query `open_interest` history จริง
- [ ] implement pair filtering จาก DB จริง

### 8.2 Platform Bridge Adapter

- [x] มี in-memory bridge ใน [platform_bridge.py](/d:/git/papertrade/src/papertrade/sources/platform_bridge.py)
- [x] เก็บ latest market state ได้
- [x] เก็บ latest orderbook ได้
- [ ] เชื่อม bridge กับ `platform` จริง
- [ ] ตัดสินใจ transport จริงว่าจะใช้ websocket / Redis / NATS / Kafka / DB snapshots
- [ ] เพิ่ม snapshot-at-cutoff logic ที่มี freshness checks

### 8.3 Liquidation Adapter

- [x] มี interface ใน [liquidation.py](/d:/git/papertrade/src/papertrade/sources/liquidation.py)
- [ ] implement source จริงของ `bybit_liquidation_amount_8h`
- [ ] เชื่อมกับ preflight ให้รู้ว่ามี source พร้อมใช้งานจริงเมื่อใด

## 9. Tests

- [x] มี [test_scheduler.py](/d:/git/papertrade/tests/test_scheduler.py)
- [x] มี [test_report_naming.py](/d:/git/papertrade/tests/test_report_naming.py)
- [x] มี [test_rules.py](/d:/git/papertrade/tests/test_rules.py)
- [x] มี [test_runtime.py](/d:/git/papertrade/tests/test_runtime.py)
- [x] มี [test_portfolio.py](/d:/git/papertrade/tests/test_portfolio.py)
- [x] มี [test_scoring.py](/d:/git/papertrade/tests/test_scoring.py)
- [x] scheduler rounds test ผ่าน
- [x] decision cutoff test ผ่าน
- [x] Windows-safe filename rendering test ผ่าน
- [x] blocked semantics test ผ่าน
- [x] close_reason invariant test ผ่าน
- [x] three-round lifecycle test ผ่าน
- [x] settlement error test ผ่าน
- [x] generic scoring test ผ่าน
- [ ] pair filtering test
- [ ] lag funding features test
- [ ] research acceptance vector test
- [ ] report writer error -> `failed` test
- [ ] integration test กับ source จริง

## 10. Phase Checklist

### Phase 0: Bootstrap Repo

- [x] สร้าง `pyproject.toml`
- [x] สร้าง package layout
- [x] สร้าง test layout
- [x] ตั้ง baseline test ให้รันได้จริง

### Phase 1: Contracts + Config + CLI Skeleton

- [x] เขียน Python dataclasses สำหรับ domain contract
- [x] เขียน config loader
- [x] เขียน CLI skeleton
- [x] เขียน preflight blocked semantics ขั้นต้น

### Phase 2: Source Adapters

- [x] นิยาม DB adapter interface
- [x] นิยาม in-memory bridge interface
- [x] นิยาม liquidation interface
- [ ] implement DB adapter จริง
- [ ] implement bridge จริง
- [ ] implement liquidation source จริง

### Phase 3: Scheduler + Feature Builder

- [x] เขียน funding round scheduler
- [x] เขียน feature builder ขั้นต้น
- [ ] เขียน snapshot collector
- [ ] เขียน lag feature loader จาก source จริง

### Phase 4: Scoring + Rules

- [x] มี generic logistic scoring engine
- [x] มี rule evaluator
- [ ] โหลด research artifacts จริง
- [ ] เทียบ score กับ acceptance vector จริง

### Phase 5: Portfolio + Reports

- [x] มี portfolio lifecycle ขั้นต้น
- [x] มี report filename/render ขั้นต้น
- [ ] เขียน markdown/csv/parquet outputs จริง
- [ ] persistence run/trade/report จริง

### Phase 6: Hardening

- [x] มี blocked semantics ขั้นต้น
- [x] มี invariant checks บางส่วน
- [ ] เพิ่ม failed semantics หลัง runtime exception
- [ ] เพิ่ม replay / integration tests

## 11. Blockers สำหรับ Exact Forward Hybrid

- [ ] `platform` ต้อง expose live `MarketState`
- [ ] `platform` ต้อง expose live `Orderbook`
- [ ] ต้องมี liquidation source สำหรับ `bybit_liquidation_amount_8h`
- [ ] ต้องมี full-precision risky artifact
- [ ] ต้องมี full-precision safe artifact

ตราบใดที่ blocker เหล่านี้ยังไม่ปิด:
- [x] repo นี้ยังพัฒนา scheduler / scoring / rules / portfolio / report pipeline ต่อได้
- [x] CLI ต้องยัง block exact run ได้อย่างถูกต้อง
- [ ] exact forward run ของ `hybrid_aggressive_safe_valid` ยังไม่ถือว่าใช้งานได้จริง

## 12. Definition Of Done สำหรับ Phase แรก

- [x] repo มี runnable core modules
- [x] repo มี CLI skeleton
- [x] repo มี unittest suite และรันผ่าน
- [x] repo มี blocked semantics ขั้นต้น
- [ ] load universe จาก `instruments` จริงได้
- [ ] รับ live-compatible `MarketState` และ `Orderbook` จาก `platform` จริงได้
- [ ] คำนวณ score จาก full-precision artifact จริงได้
- [ ] ผ่าน acceptance vector จาก research
- [ ] เปิด/ปิด position ตาม 3 funding rounds ด้วย source จริงได้
- [ ] เขียน markdown + csv/parquet artifacts ได้จริง
- [ ] แยก blocked / failed / finished semantics ได้ครบ

## 13. งานถัดไปที่ควรทำ

- [ ] แก้ `pyproject.toml` ให้ packaging entrypoint ชี้ `papertrade.cli:main`
- [ ] implement `platform_db.py` ให้ query `instruments`, `funding`, `open_interest`
- [ ] เพิ่ม `SnapshotCollector` ที่ผูกกับ `platform_bridge.py`
- [ ] export full-precision model artifacts จาก research repo
- [ ] เพิ่ม research acceptance vector test
- [ ] เขียน markdown/csv writer ลง disk จริง
