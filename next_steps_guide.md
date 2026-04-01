# Next Steps Guide: papertrade

เอกสารนี้ตอบคำถามว่า "จากโค้ดที่มีอยู่ตอนนี้ ควรทำอะไรต่อทีละ step"

แนวคิดของ guide นี้:

- เรียงงานตาม dependency จริงของระบบ
- เริ่มจากงานเล็กที่ปลดล็อกเร็ว
- แต่ละ step บอกว่าแก้ไฟล์ไหน
- แต่ละ step มีเป้าหมายชัดเจน
- แต่ละ step มีวิธีเช็กผล

## เป้าหมายรวม

ทำให้ repo นี้ขยับจาก "scaffold ที่มีชิ้นส่วนหลัก" ไปเป็น "ระบบที่รัน flow ได้จริงมากขึ้น"

## Step 1: แก้ CLI entrypoint ให้ใช้งานได้จริง

### เป้าหมาย

ให้คำสั่ง `uv run papertrade run-forward` ใช้งานได้

### ทำไมต้องทำก่อน

ตอนนี้จุดเริ่มต้นของโปรแกรมยัง wiring ไม่ตรงกับโค้ดจริง ถ้าไม่แก้ จุดรันหลักของ package จะยังพังอยู่

### ไฟล์ที่เกี่ยวข้อง

- `pyproject.toml`
- `src/papertrade/cli.py`

### สิ่งที่ต้องทำ

ใน `pyproject.toml`

- เปลี่ยน `papertrade.cli:app`
- ให้เป็น `papertrade.cli:main`

ดูให้แน่ใจว่า `cli.py` มี `main()` และ return exit code ได้ถูกต้อง

### วิธีเช็กผล

```powershell
uv run papertrade run-forward
```

ผลที่คาดหวัง:

- คำสั่งไม่พังด้วย `ImportError`
- ถ้ายังไม่มี liquidation source มันควร block ด้วยเหตุผลเดิม ไม่ใช่พังก่อนถึง logic

## Step 2: เพิ่ม test สำหรับ CLI path จริง

### เป้าหมาย

ให้ test จับได้ว่าจุดเริ่มต้นของโปรแกรมยังใช้งานได้

### ทำไมต้องทำตอนนี้

ถ้าไม่มี test สำหรับ path นี้ ปัญหา entrypoint จะกลับมาได้อีกง่ายมาก

### ไฟล์ที่เกี่ยวข้อง

- `tests/`
- อาจเพิ่ม `tests/test_cli.py`

### สิ่งที่ต้องทำ

เพิ่ม test อย่างน้อย 2 แบบ:

1. test ว่า parser รับ `run-forward` ได้
2. test ว่า `main()` เรียก `run_forward()` แล้วได้ exit code ที่คาดหวัง

ถ้าจะง่าย ให้เริ่มจาก test ระดับ function ก่อน ไม่จำเป็นต้องยิง subprocess ทันที

### วิธีเช็กผล

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```

## Step 3: แยก logic ตรวจ source availability ออกจาก CLI

### เป้าหมาย

เลิก hardcode `has_liquidation_source=False` ใน CLI

### ทำไมต้องทำ

ตอนนี้ CLI block ตลอดเพราะส่ง `False` ตายตัว ทำให้ preflight ไม่มีความหมายในเชิงระบบจริง

### ไฟล์ที่เกี่ยวข้อง

- `src/papertrade/cli.py`
- `src/papertrade/runtime.py`
- `src/papertrade/sources/liquidation.py`

### สิ่งที่ต้องทำ

เพิ่ม abstraction ง่าย ๆ ก่อน เช่น:

- ฟังก์ชันตรวจว่า liquidation source พร้อมไหม
- ฟังก์ชันตรวจว่า model artifacts พร้อมไหม

เริ่มจาก mock / in-memory / placeholder ได้ แต่ต้องแยกออกจาก CLI

เป้าหมายของ step นี้ไม่ใช่ทำ source จริงทันที

เป้าหมายคือ:

- ให้ CLI ถาม runtime/helper ว่า source พร้อมไหม
- ไม่ใช่ hardcode ค่าด้วยตัวเอง

### วิธีเช็กผล

ควรมี 3 กรณี:

1. source ไม่มี -> blocked
2. source มี แต่ artifact ไม่มี -> blocked
3. source มี และ artifact มี -> ready

## Step 4: ทำ orchestrator แบบเล็กที่สุด

### เป้าหมาย

สร้าง flow กลางที่ต่อชิ้นส่วนสำคัญเข้าด้วยกัน

### ทำไมต้องทำ

ตอนนี้มีชิ้นส่วนเยอะ แต่ยังไม่มีตัวกลางที่ทำให้เห็นภาพว่า runtime ทำงานจากต้นจนจบยังไง

### ไฟล์ที่เกี่ยวข้อง

- อาจเพิ่มไฟล์ใหม่ เช่น `src/papertrade/orchestrator.py`
- `src/papertrade/cli.py`

### สิ่งที่ต้องทำ

เริ่มจาก orchestrator เวอร์ชันเล็กที่สุดก่อน:

1. รับ `Settings`
2. คำนวณ funding round จาก scheduler
3. สร้างหรือรับ snapshot input
4. เรียก feature builder
5. เรียก scoring
6. เรียก rule evaluator
7. คืนผลลัพธ์ออกมา

ยังไม่ต้องทำ full loop แบบฟังตลาดสดตลอดเวลา

ทำแค่ "single-cycle flow" ให้จบก่อน

### วิธีเช็กผล

ควรมี function เดียวที่เรียกแล้วได้ผลลัพธ์ประมาณนี้:

- feature ถูกสร้าง
- score ถูกคำนวณ
- decision ถูกคืนกลับมา

## Step 5: ทำ snapshot collector

### เป้าหมาย

สร้างชั้นที่ดึงข้อมูลจาก source adapters มาเป็น `FundingRoundSnapshot`

### ทำไมต้องทำ

ตอนนี้ `FeatureBuilder` ต้องการ snapshot ที่ค่อนข้างพร้อม แต่ยังไม่มีตัวสร้าง snapshot กลาง

### ไฟล์ที่เกี่ยวข้อง

- `src/papertrade/feature_store.py`
- `src/papertrade/sources/platform_bridge.py`
- อาจเพิ่มไฟล์ใหม่ เช่น `src/papertrade/snapshot_collector.py`

### สิ่งที่ต้องทำ

collector ควรรับข้อมูลอย่างน้อยจาก:

- market state
- orderbook
- liquidation source

แล้วสร้าง `FundingRoundSnapshot` ของแต่ละ exchange

เริ่มจาก in-memory bridge ก่อนก็พอ

### วิธีเช็กผล

ใส่ input ตัวอย่างเข้า bridge แล้ว collector ควรสร้าง snapshot ที่:

- มี pair ถูกต้อง
- มีราคา/oi/book data ถูกต้อง
- mark `snapshot_valid` ได้ถูกต้อง

## Step 6: ทำ model artifact ให้เป็นของจริงขึ้น

### เป้าหมาย

ให้ scoring ไม่ใช่แค่โครง แต่ผูกกับ artifact จริงได้

### ทำไมต้องทำ

ตอนนี้ scoring engine ทำงานได้ แต่ยังขาด artifact จริง และ threshold ยังไม่วิ่งจาก artifact ไปถึง rule evaluator

### ไฟล์ที่เกี่ยวข้อง

- `src/papertrade/scoring.py`
- `src/papertrade/rules.py`
- `src/papertrade/config.py`

### สิ่งที่ต้องทำ

อย่างน้อยควรปิด gap 2 จุด:

1. โหลด risky/safe artifact จาก path จริง
2. ให้ threshold มาจาก artifact หรือ config เดียวกัน ไม่ hardcode ซ้ำอีกชั้น

### วิธีเช็กผล

มี test ที่ยืนยันว่า:

- เปลี่ยน threshold ใน artifact แล้ว behavior เปลี่ยนจริง
- score ถูกใส่ใน `FeatureSnapshot`

## Step 7: ทำ portfolio ให้ correctness แน่นขึ้น

### เป้าหมาย

ทำให้ simulation ไม่รับข้อมูลผิดลำดับหรือผิดเวลาแบบเงียบ ๆ

### ทำไมต้องทำ

ตอนนี้ `PortfolioSimulator` ใช้งานได้พื้นฐาน แต่ยังเปิดช่องให้ settle รอบผิดเวลา หรือผิดลำดับแล้ว position ปิดได้

### ไฟล์ที่เกี่ยวข้อง

- `src/papertrade/portfolio.py`
- `src/papertrade/contracts.py`
- `tests/test_portfolio.py`

### สิ่งที่ต้องทำ

เพิ่ม guard อย่างน้อยเรื่อง:

- ห้าม settle ก่อน `entry_round`
- ห้าม settle ย้อนเวลา
- ห้าม settle เกิน `planned_exit_round` โดยไม่มีเหตุผล
- อัปเดต `max_drawdown_pct`

### วิธีเช็กผล

เพิ่ม test สำหรับ:

- settlement ลำดับผิด
- settlement ซ้ำ
- equity ลดแล้ว drawdown ถูกอัปเดต

## Step 8: เขียน report/persistence pipeline จริง

### เป้าหมาย

ให้ผลการรันถูกเขียนออก disk ได้จริง

### ทำไมต้องทำหลังสุด

ถ้ายังไม่มั่นใจว่า runtime behavior ถูกต้อง การเขียน output ลง disk จะเป็นแค่เก็บผลที่ยังไม่น่าเชื่อถือ

### ไฟล์ที่เกี่ยวข้อง

- `src/papertrade/report.py`
- `src/papertrade/persistence.py`
- อาจเพิ่ม writer ใหม่

### สิ่งที่ต้องทำ

อย่างน้อยควรมี:

- markdown summary writer
- trade log writer
- run metadata writer

### วิธีเช็กผล

หลัง run หนึ่งรอบ ควรได้ไฟล์ใน output dir ที่เปิดอ่านได้จริง

## Step 9: ค่อยเพิ่ม source adapter จริง

### เป้าหมาย

เชื่อมระบบเข้ากับ platform/data source จริง

### ทำไมต้องทำทีหลัง

ถ้า runtime flow ภายในยังไม่แน่น การเชื่อม external dependency เร็วเกินไปจะทำให้ debug ยากมาก

### ไฟล์ที่เกี่ยวข้อง

- `src/papertrade/sources/platform_db.py`
- `src/papertrade/sources/platform_bridge.py`
- `src/papertrade/sources/liquidation.py`

### สิ่งที่ต้องทำ

เริ่มจาก adapter ทีละตัว:

1. instruments
2. funding history
3. open interest history
4. live market state/orderbook
5. liquidation source

## ลำดับที่แนะนำจริง ๆ

ถ้าจะทำแบบ pragmatic ให้ไปตามนี้:

1. Step 1: แก้ CLI entrypoint
2. Step 2: เพิ่ม CLI tests
3. Step 3: แยก source availability check
4. Step 4: ทำ orchestrator แบบ single-cycle
5. Step 5: ทำ snapshot collector
6. Step 6: ผูก scoring กับ artifact จริง
7. Step 7: harden portfolio
8. Step 8: ทำ report/persistence
9. Step 9: ค่อยเชื่อม source จริง

## ถ้าจะเริ่มลงมือ "ตอนนี้เลย"

งานที่ควรทำตอนนี้ที่สุดคือ:

### งานแรก

แก้ `pyproject.toml` ให้ `papertrade = "papertrade.cli:main"`

### งานถัดไปทันที

เพิ่ม `tests/test_cli.py`

### เหตุผล

สองงานนี้:

- เล็ก
- เห็นผลเร็ว
- ปลดบล็อก path การรันจริง
- ทำให้คุณเริ่มจับ flow ของระบบจากจุด entry ได้ชัดที่สุด

## คำแนะนำในการเรียนรู้ระบบระหว่างทำ

ทุก step ให้ถามตัวเอง 3 ข้อ:

1. input ของ step นี้คืออะไร
2. output ของ step นี้คืออะไร
3. step นี้พึ่งพาใคร และถูกใช้ต่อโดยใคร

ถ้าตอบ 3 ข้อนี้ได้ คุณจะเข้าใจระบบเร็วมากกว่าการอ่านโค้ดแบบไล่ทีละไฟล์อย่างเดียว

