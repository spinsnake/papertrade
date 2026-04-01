# Implementation Plan: Forward Paper Trade ใน `D:\git\papertrade`

## 1. เป้าหมาย

โปรเจกต์นี้ต้องสร้าง Python application สำหรับ `forward paper trade` โดยใช้ data contract ที่สอดคล้องกับ `platform`

กลยุทธ์เริ่มต้น:
- entry rule: `safe_score >= 0.151704` และ `risky_score >= 0.2071180075`
- exit rule: ถือจนรับ funding ครบ `3 funding rounds`
- ไม่ส่ง order จริง
- ต้องได้ trade log, equity curve, cost breakdown, และ markdown report

เป้าหมายหลักของ repo นี้:
- อ่าน universe และ market data จาก source ที่เข้ากันได้กับ `platform`
- คำนวณ feature/score แบบ deterministic
- จำลอง position lifecycle แบบ forward ตาม funding round จริง
- เก็บ artifact สำหรับ audit ย้อนหลังได้

สิ่งที่ไม่ทำใน phase แรก:
- live execution
- order routing
- exchange account sync
- position reconciliation กับ exchange จริง

## 2. Canonical Data Contract ที่ต้องยึด

Python implementation ต้อง mirror contract จาก Go types ต่อไปนี้

### 2.1 Instrument

source of truth สำหรับ universe และ contract constraints

fields ที่ต้องใช้:
- `exchange`
- `base`
- `quote`
- `margin_asset`
- `contract_multiplier`
- `tick_size`
- `lot_size`
- `min_qty`
- `max_qty`
- `min_notional`
- `max_leverage`
- `funding_interval`
- `launch_time`

invariant:
- pair identity = `(base, quote)`
- symbol = `base + quote`
- รองรับเฉพาะ pair ที่ `funding_interval = 8`

### 2.2 MarketState

source หลักของ:
- `index_price`
- `mark_price`
- `funding_rate`
- `open_interest`
- `base_volume`
- `quote_volume`
- `updated_at`

invariant:
- `updated_at` ต้องเป็น UTC
- ใช้ `Decimal` ฝั่ง Python ทั้งหมด ห้าม cast เป็น float ใน core path

### 2.3 Orderbook / Level

source หลักของ:
- best bid/ask price
- best bid/ask size
- book imbalance
- orderbook freshness

invariant:
- ใช้เฉพาะ top level ใน phase แรก
- ถ้า bid หรือ ask หาย ให้ row นั้น `entry_not_evaluable`

### 2.4 Funding / OpenInterest

สอง table นี้ใช้เป็น historical audit source และช่วยเติม lag features ได้

หมายเหตุสำคัญ:
- `funding.time` และ `open_interest.time` เป็น capture time
- ห้ามใช้สอง table นี้ derive canonical funding round โดยตรง
- funding round ต้อง derive จาก scheduler กลางของ paper trade

## 3. Source Mode ที่ต้องล็อก

repo นี้ควรมี source mode เดียวใน phase แรก:
- `platform_forward`

ความหมายของ `platform_forward`:
- universe มาจาก `instruments`
- historical lag metrics มาจาก `funding` และ `open_interest`
- live `MarketState` และ `Orderbook` ต้องมาจาก stream/bridge/persisted snapshot ที่มาจาก `platform`

ข้อเท็จจริงที่ต้องล็อกในแผน:
- จาก types ที่ให้มา `MarketState` กับ `Orderbook` ยังเป็น in-memory contract
- ถ้า `platform` ยังไม่ expose snapshot feed หรือ persisted snapshot table ออกมา
  Python repo นี้ยังทำ exact forward hybrid ไม่ได้
- liquidation source ยังไม่อยู่ใน types ที่ให้มา
  ดังนั้น exact hybrid mode ยังมี blocker จนกว่าจะเพิ่ม liquidation source contract

## 4. Technical Decision สำหรับ Python Repo

stack ที่แนะนำ:
- Python `3.12`
- package manager: `uv`
- config: `pydantic-settings`
- CLI: `typer`
- logging: `structlog`
- storage/query: `sqlalchemy` + `psycopg`
- dataframe/report analysis: `pandas` เฉพาะ reporting path
- serialization: `orjson`
- testing: `pytest`

หลักการ implementation:
- domain layer ใช้ `dataclass` + `Decimal`
- IO layer แยกจาก domain logic
- score logic ต้อง pure function
- report writer แยกจาก simulator
- ทุก path ที่เกี่ยวกับเงินหรือ bps ห้ามใช้ float

## 5. โครงสร้างไฟล์ที่ควรสร้าง

```text
D:\git\papertrade\
  implementation_plan.md
  pyproject.toml
  README.md
  .env.example
  src\papertrade\
    __init__.py
    cli.py
    config.py
    contracts.py
    enums.py
    scheduler.py
    feature_store.py
    scoring.py
    rules.py
    portfolio.py
    report.py
    persistence.py
    sources\
      __init__.py
      platform_db.py
      platform_bridge.py
      liquidation.py
    models\
      __init__.py
      instrument.py
      market_state.py
      orderbook.py
      funding.py
      open_interest.py
      paper_trade.py
  tests\
    test_scheduler.py
    test_scoring.py
    test_rules.py
    test_portfolio.py
    test_report_naming.py
    test_invariants.py
```

## 6. Python Domain Model ที่ต้องมี

ไฟล์ `contracts.py` ต้องนิยาม Python model ให้ตรงกับ Go contract

ขั้นต่ำ:
- `Pair`
- `Instrument`
- `Level`
- `Orderbook`
- `MarketState`
- `Funding`
- `OpenInterest`
- `FundingRoundSnapshot`
- `FeatureSnapshot`
- `EntryDecision`
- `PaperPosition`
- `PaperTrade`
- `PaperRun`

กติกา:
- `Pair.symbol` ต้องคืนค่า `base + quote`
- ใช้ `Decimal` ทุก field ที่เป็น numeric market data
- timestamp ใช้ `datetime` แบบ timezone-aware เสมอ

## 7. Forward Runtime Flow

runtime flow ที่ต้องทำมีดังนี้:

1. load config
2. connect source ของ `platform_forward`
3. load universe จาก `instruments`
4. filter pair ให้เหลือเฉพาะ:
   - `quote = USDT`
   - มีทั้ง `bybit` และ `bitget`
   - `funding_interval = 8`
5. preflight:
   - model artifact ครบ
   - source ของ `MarketState` พร้อม
   - source ของ `Orderbook` พร้อม
   - liquidation source พร้อม ถ้าจะใช้ exact hybrid
6. start funding round scheduler
7. ที่ทุก `decision_cutoff = funding_round - 30s`
   - collect latest valid snapshots
   - build features
   - compute scores
   - settle open positions ของ round นั้น
   - evaluate entries ใหม่
   - write artifacts

## 8. Funding Round Contract

canonical round:
- `00:00:00Z`
- `08:00:00Z`
- `16:00:00Z`

decision cutoff:
- `funding_round - 30 seconds`

position lifecycle:
- ถ้าเข้า round `T`
- ต้องรับ funding ที่ `T`, `T+8h`, `T+16h`
- แล้วปิดทันทีหลัง settle รอบ `T+16h`

ห้าม:
- derive round จาก `funding.time`
- ใช้ future snapshot ย้อนหลังมาแทน snapshot ที่หาย

## 9. Source Adapter ที่ต้องมี

### 9.1 Platform DB Adapter

file: `src/papertrade/sources/platform_db.py`

หน้าที่:
- อ่าน `instruments`
- อ่าน historical `funding`
- อ่าน historical `open_interest`
- build lag features สำหรับ `risky_score`

ต้องมี query อย่างน้อย:
- list supported pairs
- fetch last N funding rows ต่อ pair/exchange
- fetch last N open interest rows ต่อ pair/exchange

### 9.2 Platform Bridge Adapter

file: `src/papertrade/sources/platform_bridge.py`

หน้าที่:
- รับ live `MarketState`
- รับ live `Orderbook`
- เก็บ latest snapshot ใน memory
- expose method สำหรับ snapshot at cutoff

คำถามที่ต้องปิดก่อนลงมือ:
- `platform` จะส่ง snapshot มาให้ Python อย่างไร
  ทางเลือกที่ยอมรับได้:
  - websocket bridge จาก `platform`
  - Redis / NATS / Kafka stream
  - DB table ของ round snapshots ที่ `platform` persist มาแล้ว

ถ้ายังไม่มี bridge:
- phase แรกต้องเริ่มจาก defining interface
- และทำ mock source เพื่อเขียน simulator/test ก่อน

### 9.3 Liquidation Adapter

file: `src/papertrade/sources/liquidation.py`

หน้าที่:
- ให้ค่า `bybit_liquidation_amount_8h`

สถานะตอนนี้:
- blocker ของ exact hybrid

ถ้ายังไม่มี liquidation source:
- run ต้องเป็น `blocked`
- reason = `missing_liquidation_source`

## 10. Feature Builder

feature builder ต้องสร้างอย่างน้อย:
- `current_abs_funding_spread_bps`
- `rolling3_mean_abs_funding_spread_bps`
- `lag1_current_abs_funding_spread_bps`
- `bybit_premium_bps`
- `bitget_futures_premium_bps`
- `premium_abs_gap_bps`
- `bybit_open_interest`
- `bitget_open_interest`
- `oi_gap`
- `oi_total`
- `book_imbalance_abs_gap`
- `bybit_liquidation_amount_8h`
- `signed_spread_bps`

สูตรที่ต้องใช้:

```text
current_funding_spread_bps = bybit_funding_rate_bps - bitget_funding_rate_bps
current_abs_funding_spread_bps = abs(current_funding_spread_bps)

bybit_premium_bps = (bybit_mark_price - bybit_index_price) / bybit_index_price * 10000
bitget_futures_premium_bps = (bitget_mark_price - bitget_index_price) / bitget_index_price * 10000
premium_abs_gap_bps = abs(bybit_premium_bps - bitget_futures_premium_bps)

oi_gap = bybit_open_interest - bitget_open_interest
oi_total = bybit_open_interest + bitget_open_interest

bybit_book_imbalance =
    (bybit_best_bid_size - bybit_best_ask_size) /
    (bybit_best_bid_size + bybit_best_ask_size)

bitget_book_imbalance =
    (bitget_best_bid_size - bitget_best_ask_size) /
    (bitget_best_bid_size + bitget_best_ask_size)

book_imbalance_abs_gap = abs(bybit_book_imbalance - bitget_book_imbalance)
```

## 11. Score Engine

ต้องมี score engine แยกเป็น pure module

file: `src/papertrade/scoring.py`

หน้าที่:
- load full-precision model artifacts
- compute `safe_score`
- compute `risky_score`

artifact contract ที่ต้องมี:
- feature order
- means
- stds
- weights
- bias
- thresholds

ห้าม:
- hardcode coefficients กระจายหลายไฟล์
- ใช้ค่าจาก markdown เป็น source of truth

## 12. Rule Evaluator

file: `src/papertrade/rules.py`

entry logic:

```text
selected =
  safe_score >= 0.151704 and
  risky_score >= 0.2071180075
```

exit logic:
- close after 3 collected funding rounds

direction logic:
- ถ้า spread ตอน entry เป็นบวก:
  `short bybit / long bitget`
- ถ้า spread ตอน entry เป็นลบ:
  `short bitget / long bybit`

reason codes ขั้นต่ำ:
- `selected`
- `below_safe_threshold`
- `below_risky_threshold`
- `below_both_threshold`
- `missing_market_state`
- `missing_orderbook`
- `missing_liquidation_source`
- `missing_lag_history`

## 13. Portfolio Simulator

file: `src/papertrade/portfolio.py`

ต้องรับผิดชอบ:
- open position
- settle per round
- close position
- maintain equity
- maintain drawdown
- write trade log DTO

cost model phase แรก:
- fee = `4 bps`
- slippage = `4 bps`

PnL formula:

```text
gross_bps = round1 + round2 + round3
net_bps = gross_bps - 4 - 4
net_pnl = notional * net_bps / 10000
```

invariant:
- open position -> `close_reason = None`
- closed / settlement_error -> `close_reason != None`

## 14. Persistence Strategy

แนะนำให้ Python repo เก็บ artifact ของตัวเองแยกจาก `platform`

phase แรก:
- local SQLite หรือ DuckDB สำหรับ run metadata
- CSV/Parquet สำหรับ trade log
- Markdown สำหรับ summary report

ขั้นต่ำที่ต้อง persist:
- run metadata
- funding round snapshots
- feature snapshots
- open positions
- closed trades
- report outputs

ถ้าต้องการเชื่อม Postgres ตั้งแต่แรก:
- แยก schema ของ Python repo เป็นของตัวเอง
- ห้ามเขียนทับ table ของ `platform`

## 15. Report Writer

file: `src/papertrade/report.py`

ต้องสร้าง:
- markdown summary
- csv trade log
- optional parquet trade log

filename policy:
- `{as_of_round}` ต้อง render เป็น `YYYYMMDDTHHMMSSZ`
- ห้ามใช้ RFC3339 ตรง ๆ เพราะ `:` ใช้บน Windows ไม่ได้

ตัวอย่าง:
- `hybrid_aggressive_safe_valid__paper-20260331-000000__20260331T080000Z__summary.md`

## 16. CLI

file: `src/papertrade/cli.py`

command แรกที่ควรมี:

```text
python -m papertrade.cli run-forward
```

args ขั้นต่ำ:
- `--source-mode platform_forward`
- `--report-dir`
- `--initial-equity`
- `--notional-pct`
- `--fee-bps`
- `--slippage-bps`
- `--strict-liquidation`

## 17. Test Plan

ต้องมี test ขั้นต่ำ:

- scheduler rounds เป็น `00:00Z/08:00Z/16:00Z`
- decision cutoff = round - 30s
- filename rendering เป็น Windows-safe
- pair filtering ใช้ `funding_interval = 8`
- lag funding features ถูกต้อง
- score vector เทียบค่าคาดหวังได้
- entry/exit rules ถูกต้อง
- closed position ต้องมี `close_reason`
- ถ้า liquidation source ไม่มี -> run blocked
- ถ้า report writer error หลัง preflight ผ่าน -> run failed

## 18. Phase Plan

### Phase 0: Bootstrap Repo

- สร้าง `pyproject.toml`
- สร้าง package layout
- ตั้งค่า lint/test baseline

### Phase 1: Contracts + Config + CLI Skeleton

- เขียน Python dataclasses/pydantic models
- เขียน config loader
- เขียน CLI skeleton

### Phase 2: Source Adapters

- อ่าน instruments/funding/open_interest จาก DB
- นิยาม bridge interface สำหรับ market state/orderbook
- ทำ mock source สำหรับ local test

### Phase 3: Scheduler + Feature Builder

- เขียน funding round scheduler
- เขียน snapshot collector
- เขียน feature builder

### Phase 4: Scoring + Rules

- load model artifacts
- compute scores
- evaluate entries

### Phase 5: Portfolio + Reports

- portfolio lifecycle
- markdown/csv/parquet outputs
- run status handling

### Phase 6: Hardening

- add blocked/failed semantics
- add invariant checks
- add replay tests

## 19. Blockers ที่ต้องปิดก่อนเริ่ม exact hybrid

- `platform` ต้อง expose live `MarketState`
- `platform` ต้อง expose live `Orderbook`
- ต้องมี liquidation source สำหรับ `bybit_liquidation_amount_8h`
- ต้องมี full-precision model artifact

ถ้ายังไม่ปิด blocker เหล่านี้:
- Python repo ยังเขียน simulator, scheduler, feature builder, score engine, report pipeline ได้
- แต่ exact forward run ของ `hybrid_aggressive_safe_valid` ต้องยัง mark เป็น `blocked`

## 20. Definition of Done

ถือว่า phase แรกเสร็จเมื่อ:
- repo รัน `run-forward` ได้
- load universe จาก `instruments` ได้
- รับ mock/live-compatible `MarketState` และ `Orderbook` ได้
- คำนวณ score ได้ตรงกับ acceptance vector
- เปิด/ปิด position ตาม 3 funding rounds ได้
- เขียน markdown + csv report ได้
- blocked/failed semantics ถูกต้อง
- tests สำคัญทั้งหมดผ่าน
