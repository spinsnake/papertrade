# Code Walkthrough: papertrade

เอกสารนี้อธิบายระบบใน repo นี้แบบอ่านง่าย โดยยึดจากโค้ดที่มีอยู่จริงตอนนี้

## โปรเจกต์นี้คืออะไร

`papertrade` เป็น scaffold สำหรับทำ `forward paper trade` ตามกลยุทธ์ `hybrid_aggressive_safe_valid`

ตอนนี้ระบบมีชิ้นส่วนหลักเกือบครบแล้ว เช่น

- contract / domain model
- scheduler
- feature builder
- scoring
- rule evaluator
- portfolio simulator
- report naming
- source adapter interfaces

แต่ยัง **ไม่ใช่ระบบที่รัน full loop ได้ครบจริง** เพราะ data source จริง, orchestrator, และ persistence pipeline ยังไม่ต่อครบ

## ภาพรวมระบบแบบสั้นมาก

ลำดับการทำงานที่ระบบนี้ตั้งใจจะมีคือ:

```text
CLI
-> Config
-> Preflight
-> Scheduler
-> Snapshot Collection
-> Feature Builder
-> Scoring
-> Rule Evaluator
-> Portfolio Simulator
-> Report / Persistence
```

พูดง่าย ๆ คือ:

1. รับคำสั่งจาก command line
2. โหลดค่าตั้งต้นจาก environment
3. เช็กว่าระบบพร้อมรันหรือยัง
4. คำนวณ funding round ที่เกี่ยวข้อง
5. ดึง snapshot ของตลาด
6. แปลง snapshot เป็น feature
7. ใช้โมเดลคำนวณ score
8. ตัดสินใจว่าจะเปิด position หรือไม่
9. ติดตาม funding แต่ละรอบจนปิด position
10. สร้าง report และเก็บผลลัพธ์

## โค้ดแต่ละส่วนทำอะไร

### 1. `src/papertrade/cli.py`

ไฟล์นี้คือจุดเริ่มต้นของโปรแกรม

หน้าที่หลัก:

- รับคำสั่งจาก command line
- parse arguments
- เรียก `run_forward()`
- สร้าง `PaperRun`
- เรียก preflight check
- แจ้งว่า run นี้ `ready` หรือ `blocked`

คำสั่งหลักตอนนี้คือ:

```powershell
python -m papertrade.cli run-forward
```

ข้อสำคัญ:

- ตอนนี้ CLI ยังไม่ได้เป็น full runtime loop
- มันยังแค่โหลด config, สร้าง run, และเช็ก preflight
- ถ้าขาด liquidation source และเปิด `strict_liquidation` ไว้ มันจะ block ทันที

### 2. `src/papertrade/config.py`

ไฟล์นี้รวมค่าตั้งต้นของระบบ

หน้าที่หลัก:

- อ่านค่าจาก environment variables
- สร้าง `Settings`
- validate ค่าที่สำคัญ

ตัวอย่างค่าที่เก็บไว้:

- `strategy`
- `runtime_mode`
- `initial_equity`
- `notional_pct`
- `fee_bps`
- `slippage_bps`
- `strict_liquidation`
- `risky_artifact_path`
- `safe_artifact_path`

แนวคิดของไฟล์นี้คือ:

- runtime ไม่ควรอ่าน env กระจัดกระจายหลายจุด
- ให้ทุกอย่างวิ่งผ่าน `Settings.from_env()` จุดเดียว

### 3. `src/papertrade/contracts.py`

ไฟล์นี้สำคัญมาก เพราะเป็นศูนย์รวม domain model ของระบบ

มันอธิบายว่า object หลักของระบบมีอะไรบ้าง

กลุ่มข้อมูลตลาด:

- `Pair`
- `Instrument`
- `Level`
- `Orderbook`
- `MarketState`
- `Funding`
- `OpenInterest`

กลุ่มข้อมูลสำหรับ decision:

- `FundingRoundSnapshot`
- `FeatureSnapshot`
- `EntryDecision`

กลุ่มข้อมูลสำหรับ simulation:

- `PaperPositionRound`
- `PaperPosition`
- `PaperTrade`
- `PaperRun`

ถ้าจะเข้าใจระบบนี้จริง ควรอ่านไฟล์นี้ต้น ๆ เพราะมันทำให้เห็น vocabulary ของทั้งโปรเจกต์

### 4. `src/papertrade/runtime.py`

ไฟล์นี้มีหน้าที่เช็กว่า runtime พร้อมรันหรือยัง

ฟังก์ชันหลักคือ `preflight_status(...)`

มันเช็กเรื่องสำคัญ เช่น:

- มี liquidation source หรือยัง
- มี model artifact หรือยัง

ถ้ายังไม่พร้อม มันจะคืนค่า `blocked`

แนวคิดคือ:

- อย่าปล่อยให้ระบบเริ่ม run ทั้งที่ dependency หลักยังไม่ครบ

### 5. `src/papertrade/scheduler.py`

ไฟล์นี้จัดการเรื่องเวลา

หน้าที่หลัก:

- คำนวณ funding round ถัดไป
- คำนวณ decision cutoff
- คำนวณ exit round

ระบบนี้ใช้ cadence แบบ `8 ชั่วโมง`

round มาตรฐานคือ:

- `00:00Z`
- `08:00Z`
- `16:00Z`

decision cutoff คือ:

- `funding_round - 30 seconds`

ดังนั้นไฟล์นี้คือ logic เวลาและ timing ของระบบ

### 6. `src/papertrade/feature_store.py`

ไฟล์นี้มี `FeatureBuilder`

หน้าที่คือแปลงข้อมูล snapshot ดิบให้กลายเป็น feature สำหรับ model

ตัวอย่าง feature ที่คำนวณ:

- signed spread
- premium
- premium gap
- open interest gap
- open interest total
- book imbalance gap
- liquidation amount

สรุปง่าย ๆ:

- input = snapshot จาก exchange
- output = feature vector ที่ model ใช้ได้

### 7. `src/papertrade/scoring.py`

ไฟล์นี้มี logic ของโมเดลแบบ logistic scoring

ส่วนสำคัญคือ `LogisticArtifact`

artifact หนึ่งก้อนประกอบด้วย:

- ลำดับ feature
- mean
- std
- weight
- bias
- threshold

เวลาคำนวณ:

1. ดึงค่าของแต่ละ feature
2. normalize ด้วย mean / std
3. คูณ weight
4. รวมกับ bias
5. แปลงด้วย sigmoid เป็น score

ฟังก์ชัน `compute_scores(...)` จะเอาผลที่คำนวณได้ไปใส่ใน `FeatureSnapshot`

### 8. `src/papertrade/rules.py`

ไฟล์นี้ใช้ score มาตัดสินใจว่าจะเปิด position หรือไม่

หน้าที่หลัก:

- เช็กว่า pair นี้มี position เปิดอยู่แล้วไหม
- เช็กว่า feature พร้อมใช้ไหม
- เช็กว่า score ผ่าน threshold ไหม
- กำหนด short/long direction จาก spread

rule ปัจจุบัน:

- ถ้า `safe_score` ผ่าน และ `risky_score` ผ่าน -> `selected`
- ถ้า spread เป็นบวก -> `short bybit`, `long bitget`
- ถ้า spread เป็นลบ -> `short bitget`, `long bybit`

ไฟล์นี้คือชั้น business rule ระหว่าง model output กับ portfolio

### 9. `src/papertrade/portfolio.py`

ไฟล์นี้จำลอง lifecycle ของ position

หน้าที่หลัก:

- เปิด position
- รับ funding ของแต่ละรอบ
- ปิด position หลังครบ 3 รอบ
- คำนวณ gross bps / net bps
- คำนวณ gross pnl / net pnl
- อัปเดต equity ของ run

ฟังก์ชันหลัก:

- `has_open_position(...)`
- `open_position(...)`
- `settle_round(...)`
- `_close_completed(...)`

นี่คือแกนของการจำลองผลลัพธ์การเทรด

### 10. `src/papertrade/report.py`

ไฟล์นี้จัดการเรื่อง report

หน้าที่หลัก:

- render ชื่อไฟล์ report
- ทำให้ชื่อไฟล์ปลอดภัยกับ Windows
- สร้าง markdown summary เบื้องต้น

มันยังไม่ใช่ full report pipeline แต่เป็น utility สำหรับ output

### 11. `src/papertrade/persistence.py`

ไฟล์นี้มี `JsonArtifactStore`

หน้าที่คือ:

- รับ object หรือ payload
- แปลงเป็น JSON
- เขียนลง disk

ตอนนี้เป็น persistence แบบง่ายที่สุดก่อน

### 12. `src/papertrade/sources/`

โฟลเดอร์นี้เก็บ adapter interface ของ source ต่าง ๆ

ไฟล์สำคัญ:

- `platform_db.py`
- `platform_bridge.py`
- `liquidation.py`

สิ่งที่มีตอนนี้:

- interface / protocol
- in-memory bridge สำหรับ market state และ orderbook

สิ่งที่ยังไม่มี:

- adapter จริงที่ไป query database
- bridge จริงกับ platform
- liquidation source จริง

## ถ้าอยากอ่านโค้ดให้เข้าใจเร็ว ควรอ่านตามลำดับนี้

### รอบที่ 1: อ่านภาพรวม

1. `src/papertrade/cli.py`
2. `src/papertrade/config.py`
3. `src/papertrade/contracts.py`

เป้าหมาย:

- รู้ว่าระบบเริ่มยังไง
- รู้ว่าค่าตั้งต้นมาจากไหน
- รู้ว่า object หลักของระบบมีอะไรบ้าง

### รอบที่ 2: อ่าน logic หลัก

1. `src/papertrade/runtime.py`
2. `src/papertrade/scheduler.py`
3. `src/papertrade/feature_store.py`
4. `src/papertrade/scoring.py`
5. `src/papertrade/rules.py`

เป้าหมาย:

- รู้ว่า decision ถูกสร้างขึ้นยังไง
- รู้ว่า data ดิบกลายเป็น score ได้ยังไง

### รอบที่ 3: อ่าน simulation และ output

1. `src/papertrade/portfolio.py`
2. `src/papertrade/report.py`
3. `src/papertrade/persistence.py`

เป้าหมาย:

- รู้ว่า position ถูกเปิด/ปิดยังไง
- รู้ว่าผลลัพธ์จะถูกสรุปและเก็บยังไง

## สถานะปัจจุบันของระบบ

ตอนนี้ repo นี้มีสิ่งที่ "มีแล้ว" และ "ยังไม่ครบ" ชัดเจน

มีแล้ว:

- domain model
- scheduler
- feature builder
- scoring engine
- rule evaluator
- portfolio simulator
- test พื้นฐาน

ยังไม่ครบ:

- live data source จริง
- liquidation source จริง
- orchestrator ที่รัน full loop
- persistence/report pipeline แบบครบ
- integration กับ platform จริง

## สรุปแบบสั้น

ถ้าจะอธิบายระบบนี้ในประโยคเดียว:

> โปรเจกต์นี้เป็นโครงของระบบ paper trade ที่แยกชิ้นส่วนหลักไว้ครบพอสมควร แต่ยังขาดตัวเชื่อมและ source จริงเพื่อให้รัน end-to-end ได้จริง

## แนะนำขั้นถัดไปในการศึกษา

ถ้าจะอ่านต่อให้เข้าใจลึกขึ้น ผมแนะนำให้ทำทีละไฟล์แบบนี้:

1. อ่าน `cli.py` ให้จบ
2. อ่าน `config.py`
3. อ่าน `contracts.py`
4. กลับมาดู flow `preflight -> scheduler -> feature -> scoring -> rules`
5. จบด้วย `portfolio.py`

หลังจากนั้นค่อยดู test เพื่อยืนยันความเข้าใจ

