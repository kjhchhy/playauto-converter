# SQLite DB Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a SQLite-backed product/listing database, crawl import with price history, and DB-driven setting/final xlsx export without changing the existing direct xlsx converter.

**Architecture:** `products` stores base products, `listings` stores bundle sale units, and `price_history` records every imported listing price. Import upserts products by `order_url` and qty-1 listings, preserving user-edited fields. Export joins active listings to products, writes a new `setting` sheet into a copy of the reference workbook, then reuses `convert_phase1(setting_path, output_dir, selected_option, coupang_single, commission, run_date, copy_setting=False)` for final files.

**Tech Stack:** Python 3.12 stdlib `sqlite3`, `unittest`, vendored `openpyxl`.

**Spec:** `docs/superpowers/specs/2026-10-27-crawl-to-setting-design.md`

## Global Constraints

- No new dependencies; use stdlib `sqlite3` and the existing vendored `openpyxl`.
- Default DB path is `data/playauto.db`; every DB command accepts `--db`.
- `template` sheet must never be modified by our code.
- Setting `템플릿코드정보` is always `1박스`.
- `products.order_url` is stored in DB and in the internal setting's last column (`주문링크`); it must not appear in final `_단일/_일반/_쿠팡` files.
- Margins are ratios in `[0, 1)`; reuse `parse_margin_ratio` behavior for crawl values.
- Existing direct CLI (`run_converter.py <xlsx> ...`) must keep working unchanged.
- Tests use `unittest`, not pytest.
- This workspace is not a git repository; end each task with the listed test checkpoint instead of a commit.

## Review Focus

- Re-crawling an existing URL with changed price/name/image must update crawl fields but preserve user edits to category, detail, metadata, listing margin, sale name, unit-price fields, active, and seller code. Covered by Task 2.
- A user-created `bundle_qty=2/3` listing must not be touched by import and must be exported as its own setting row. Covered by Tasks 2 and 4.
- Missing or malformed crawl cells (blank required value, bad price, bad sequence, missing header) must fail with row/header context, not silently drop products. Covered by Task 1.
- Reference workbook `template` and other sheets must retain their values and styles while only `setting` is replaced. Covered by Task 3.
- An invalid DB row must fail validation before any setting/final file is written. Covered by Task 4.

---

### Task 1: DB schema and crawl loader

**Files:**
- Create: `playauto/db.py`
- Create: `tests/test_db.py`

**Interfaces:**
- Consumes: stdlib `sqlite3`, `dataclasses`, `datetime`, `pathlib`, `openpyxl.load_workbook`.
- Produces:
  - `DEFAULT_DB_PATH = Path("data/playauto.db")`
  - `SCHEMA_VERSION = 1`
  - `REQUIRED_HEADERS = ("순번", "대표이미지", "상품명", "판매가격", "URL")`
  - `OPTIONAL_HEADERS = ("판매자관리코드", "마진율", "상세설명", "키워드", "제조사", "브랜드", "모델명", "단위 가격 표시 여부", "표시 용량", "표시 단위", "개당 용량", "구성 방식")`
  - `connect(db_path: str | Path) -> sqlite3.Connection`
  - `ensure_schema(conn: sqlite3.Connection) -> None`
  - `CrawlRow` frozen dataclass with fields: `source_seq: int`, `name: str`, `market_price: int`, `image_url: str`, `order_url: str`, `seller_code: str | None = None`, `margin_rate: float | None = None`, `detail: str | None = None`, `keywords: str | None = None`, `manufacturer: str | None = None`, `brand: str | None = None`, `model: str | None = None`, `unit_price_visible: str | None = None`, `display_capacity: str | None = None`, `display_unit: str | None = None`, `pack_config: str | None = None`, `capacity_per_unit: str | None = None`
  - `CrawlData` frozen dataclass with `rows: tuple[CrawlRow, ...]`, `skipped: int`
  - `parse_price(value) -> int`
  - `load_crawl_rows(path: str | Path) -> CrawlData`

- [ ] **Step 1: Write the failing schema/loader tests**

Create `tests/test_db.py` with this fixture and test class:

```python
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook

from playauto.db import (
    CrawlData,
    CrawlRow,
    connect,
    ensure_schema,
    load_crawl_rows,
    parse_price,
)

REQUIRED = ["순번", "대표이미지", "상품명", "판매가격", "URL"]
OPTIONAL = [
    "판매자관리코드", "마진율", "상세설명", "키워드", "제조사", "브랜드", "모델명",
    "단위 가격 표시 여부", "표시 용량", "표시 단위", "개당 용량", "구성 방식",
]


def make_crawl(path, headers=None, rows=None):
    wb = Workbook()
    ws = wb.active
    ws.append(headers or [*REQUIRED, *OPTIONAL])
    for row in rows or []:
        ws.append(row)
    wb.save(path)


class DbSchemaTests(unittest.TestCase):
    def test_ensure_schema_creates_tables_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            ensure_schema(conn)
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertTrue(
                {"products", "listings", "price_history", "import_batches"} <= names
            )
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            conn.close()

    def test_load_crawl_rows_maps_optional_columns_and_counts_blank_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crawl.xlsx"
            make_crawl(
                path,
                rows=[
                    [
                        1, "https://img/1.jpg", "상품1", "10,000원", "https://order/1",
                        "MJ-X", "15%", "상세", "kw", "제조", "브랜드", "모델",
                        "Y", "500", "ml", "250", "묶음",
                    ],
                    [None] * (len(REQUIRED) + len(OPTIONAL)),
                ],
            )
            data = load_crawl_rows(path)

        self.assertIsInstance(data, CrawlData)
        self.assertEqual(len(data.rows), 1)
        self.assertEqual(data.skipped, 1)
        row = data.rows[0]
        self.assertEqual(row.source_seq, 1)
        self.assertEqual(row.name, "상품1")
        self.assertEqual(row.market_price, 10000)
        self.assertEqual(row.image_url, "https://img/1.jpg")
        self.assertEqual(row.order_url, "https://order/1")
        self.assertEqual(row.seller_code, "MJ-X")
        self.assertEqual(row.margin_rate, 0.15)
        self.assertEqual(row.pack_config, "묶음")
        self.assertEqual(row.capacity_per_unit, "250")

    def test_load_crawl_rows_rejects_missing_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crawl.xlsx"
            make_crawl(
                path,
                headers=["순번", "대표이미지", "상품명", "판매가격"],
                rows=[[1, "img", "상품1", 1000]],
            )
            with self.assertRaisesRegex(ValueError, "누락 헤더.*URL"):
                load_crawl_rows(path)

    def test_load_crawl_rows_rejects_blank_required_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crawl.xlsx"
            make_crawl(
                path,
                rows=[[1, "img", None, 1000, "https://order/1"]],
            )
            with self.assertRaisesRegex(ValueError, "2행.*상품명"):
                load_crawl_rows(path)

    def test_load_crawl_rows_rejects_bad_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crawl.xlsx"
            make_crawl(
                path,
                rows=[["abc", "img", "상품1", 1000, "https://order/1"]],
            )
            with self.assertRaisesRegex(ValueError, "2행.*순번"):
                load_crawl_rows(path)

    def test_load_crawl_rows_rejects_bad_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crawl.xlsx"
            make_crawl(
                path,
                rows=[[1, "img", "상품1", "가격없음", "https://order/1"]],
            )
            with self.assertRaisesRegex(ValueError, "2행.*판매가격"):
                load_crawl_rows(path)

    def test_parse_price_accepts_commas_and_won(self):
        self.assertEqual(parse_price("10,000원"), 10000)
        self.assertEqual(parse_price(7080), 7080)
        with self.assertRaises(ValueError):
            parse_price("가격없음")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
& 'C:\Users\kjhch\AppData\Local\Temp\py312\py\python.exe' -m unittest tests.test_db -v
```

Expected: import error for `playauto.db`.

- [ ] **Step 3: Implement schema and loader in `playauto/db.py`**

Create the module with these exact tables and helpers:
- `connect`: create parent directory, `sqlite3.connect`, `row_factory = sqlite3.Row`, `PRAGMA foreign_keys=ON`.
- `ensure_schema`: `executescript` creating `products`, `import_batches`, `listings`, `price_history`, and indexes on `listings(active)`, `listings(product_id)`, `products(source_seq)`; then `PRAGMA user_version=1`.
- `products`: `id`, `source_seq`, `name`, `image_url`, `order_url UNIQUE`, `category_code`, `detail`, `keywords`, `manufacturer`, `brand`, `model`, `created_at`, `updated_at`, `last_seen_at`, `last_batch_id`.
- `listings`: `id`, `product_id REFERENCES products(id)`, `seller_code UNIQUE`, `bundle_qty DEFAULT 1`, `sale_name`, `market_price`, `margin_rate DEFAULT 0.15`, five unit-price columns, `active DEFAULT 1`, `created_at`, `updated_at`, `UNIQUE(product_id, bundle_qty)`.
- `price_history`: `id`, `product_id`, `listing_id`, `price`, `observed_at`, `batch_id`, `crawl_path`.
- `import_batches`: `id`, `imported_at`, `crawl_path`, `row_count`, `inserted_count`, `updated_count`, `skipped_count`.
- `parse_price`: strip whitespace, commas, and trailing `원`; convert with `int(float(text))`; raise `ValueError` on empty/non-numeric.
- `load_crawl_rows`: use the first worksheet; build a header map from stripped non-empty header strings; require `REQUIRED_HEADERS`; iterate rows 2..max; a row whose cells are all `None` or blank strings increments `skipped`; for other rows parse required values and optional columns; optional blank values become `None`; wrap price/sequence/margin errors with `[크롤] {row}행 '<header>' 값이 올바르지 않습니다.` context.

- [ ] **Step 4: Run tests to verify they pass**

Run the same command. Expected: all `DbSchemaTests` pass.

- [ ] **Step 5: Test checkpoint**

Run the full suite:

```powershell
& 'C:\Users\kjhch\AppData\Local\Temp\py312\py\python.exe' -m unittest discover -s tests -v
```

Expected: existing tests plus `DbSchemaTests` pass.

---

### Task 2: Import, upsert, and price history

**Files:**
- Modify: `playauto/db.py`
- Modify: `tests/test_db.py`

**Interfaces:**
- Consumes: `CrawlData`, `CrawlRow`, `connect`, `ensure_schema`.
- Produces:
  - `ImportSummary` frozen dataclass with `batch_id: int`, `inserted: int`, `updated: int`, `skipped: int`, `row_count: int`
  - `import_crawl(conn, crawl: CrawlData, category_code: str, margin: float, crawl_path: str) -> ImportSummary`

- [ ] **Step 1: Write the failing import tests**

Append to `tests/test_db.py`:

```python
from dataclasses import replace

from playauto.db import import_crawl


def make_row(**overrides):
    base = CrawlRow(
        source_seq=1,
        name="상품1",
        market_price=7080,
        image_url="https://img/1.jpg",
        order_url="https://order/1",
    )
    return replace(base, **overrides)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "test.db")
        ensure_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def import_rows(self, *rows):
        return import_crawl(
            self.conn,
            CrawlData(tuple(rows), 0),
            category_code="기타재화[35]",
            margin=0.15,
            crawl_path="crawl.xlsx",
        )

    def test_import_creates_product_listing_and_price_history(self):
        summary = self.import_rows(make_row())
        product = self.conn.execute("SELECT * FROM products").fetchone()
        listing = self.conn.execute("SELECT * FROM listings").fetchone()
        history = self.conn.execute("SELECT * FROM price_history").fetchone()

        self.assertEqual(summary.inserted, 1)
        self.assertEqual(product["order_url"], "https://order/1")
        self.assertEqual(product["category_code"], "기타재화[35]")
        self.assertEqual(listing["seller_code"], "MJ-0001")
        self.assertEqual(listing["bundle_qty"], 1)
        self.assertEqual(listing["market_price"], 7080)
        self.assertEqual(listing["margin_rate"], 0.15)
        self.assertEqual(listing["active"], 1)
        self.assertEqual(history["price"], 7080)

    def test_reimport_updates_crawl_fields_and_preserves_user_edits(self):
        self.import_rows(make_row())
        self.conn.execute(
            "UPDATE products SET category_code='CUSTOM', detail='D', keywords='K', "
            "manufacturer='M', brand='B', model='MO'"
        )
        self.conn.execute(
            "UPDATE listings SET margin_rate=0.2, sale_name='수정명', "
            "active=0, seller_code='USER-1', unit_price_visible='Y', "
            "display_capacity='500', display_unit='ml', pack_config='묶음', "
            "capacity_per_unit='250'"
        )
        self.conn.commit()

        self.import_rows(
            make_row(
                name="상품1-new",
                market_price=8000,
                image_url="https://img/new.jpg",
            )
        )
        product = self.conn.execute("SELECT * FROM products").fetchone()
        listing = self.conn.execute("SELECT * FROM listings").fetchone()

        self.assertEqual(product["name"], "상품1-new")
        self.assertEqual(product["image_url"], "https://img/new.jpg")
        self.assertEqual(product["category_code"], "CUSTOM")
        self.assertEqual(product["detail"], "D")
        self.assertEqual(product["keywords"], "K")
        self.assertEqual(product["manufacturer"], "M")
        self.assertEqual(product["brand"], "B")
        self.assertEqual(product["model"], "MO")
        self.assertEqual(listing["market_price"], 8000)
        self.assertEqual(listing["margin_rate"], 0.2)
        self.assertEqual(listing["sale_name"], "수정명")
        self.assertEqual(listing["active"], 0)
        self.assertEqual(listing["seller_code"], "USER-1")
        self.assertEqual(listing["unit_price_visible"], "Y")
        self.assertEqual(listing["display_capacity"], "500")
        self.assertEqual(listing["display_unit"], "ml")
        self.assertEqual(listing["pack_config"], "묶음")
        self.assertEqual(listing["capacity_per_unit"], "250")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0], 2
        )

    def test_import_does_not_touch_other_bundle_listings(self):
        self.import_rows(make_row())
        product_id = self.conn.execute("SELECT id FROM products").fetchone()[0]
        self.conn.execute(
            "INSERT INTO listings (product_id, seller_code, bundle_qty, sale_name, "
            "market_price, margin_rate, active, created_at, updated_at) "
            "VALUES (?, 'MJ-0001-2', 2, '2개묶음', 14160, 0.15, 1, 'now', 'now')",
            (product_id,),
        )
        self.conn.commit()

        self.import_rows(make_row(market_price=8000))
        bundle2 = self.conn.execute(
            "SELECT * FROM listings WHERE bundle_qty=2"
        ).fetchone()
        bundle1 = self.conn.execute(
            "SELECT * FROM listings WHERE bundle_qty=1"
        ).fetchone()

        self.assertEqual(bundle1["market_price"], 8000)
        self.assertEqual(bundle2["market_price"], 14160)
        self.assertEqual(bundle2["sale_name"], "2개묶음")

    def test_missing_qty1_listing_is_recreated(self):
        self.import_rows(make_row())
        self.conn.execute("DELETE FROM price_history")
        self.conn.execute("DELETE FROM listings")
        self.conn.commit()

        self.import_rows(make_row())
        listing = self.conn.execute("SELECT * FROM listings").fetchone()
        self.assertEqual(listing["bundle_qty"], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0], 1
        )

    def test_seller_code_collision_gets_suffix(self):
        self.import_rows(
            make_row(order_url="https://order/1"),
            make_row(order_url="https://order/2"),
        )
        codes = [
            row[0]
            for row in self.conn.execute(
                "SELECT seller_code FROM listings ORDER BY id"
            )
        ]
        self.assertEqual(codes, ["MJ-0001", "MJ-0001-2"])

    def test_duplicate_url_in_one_crawl_updates_same_product(self):
        self.import_rows(make_row(market_price=7000), make_row(market_price=7100))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0], 1
        )
        listing = self.conn.execute("SELECT * FROM listings").fetchone()
        self.assertEqual(listing["market_price"], 7100)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0], 2
        )

    def test_provided_seller_code_collision_raises(self):
        self.import_rows(make_row(seller_code="DUP"))
        with self.assertRaisesRegex(ValueError, "판매자관리코드.*중복"):
            self.import_rows(
                make_row(order_url="https://order/2", seller_code="DUP")
            )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1
        )

    def test_import_batch_counts(self):
        summary = self.import_rows(make_row(), make_row(order_url="https://order/2"))
        batch = self.conn.execute("SELECT * FROM import_batches").fetchone()
        self.assertEqual(summary.inserted, 2)
        self.assertEqual(summary.updated, 0)
        self.assertEqual(summary.skipped, 0)
        self.assertEqual(summary.row_count, 2)
        self.assertEqual(batch["inserted_count"], 2)

        summary2 = self.import_rows(make_row())
        self.assertEqual(summary2.inserted, 0)
        self.assertEqual(summary2.updated, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
& 'C:\Users\kjhch\AppData\Local\Temp\py312\py\python.exe' -m unittest tests.test_db.ImportTests -v
```

Expected: import error for `import_crawl`.

- [ ] **Step 3: Implement `import_crawl` in `playauto/db.py`**

Implementation rules:
- Wrap the entire import in `with conn:` (or an explicit `try/except` rollback) and insert the `import_batches` row with zero counts. Any error, including a provided seller-code collision or a database error, must roll back the whole import so no partial product/listing/history rows remain.
- For each `CrawlRow`: use one `now` timestamp per import.
- Upsert product by `order_url`. New product inserts `source_seq`, `name`, `image_url`, `order_url`, `category_code`, optional detail/metadata, timestamps, `last_batch_id`. Existing product updates only `source_seq`, `name`, `image_url`, `last_seen_at`, `last_batch_id`, `updated_at`.
- Find qty-1 listing by `product_id` and `bundle_qty=1`. New listing uses provided `seller_code` or `MJ-{source_seq:04d}`; if a generated code collides, append `-2`, `-3`, etc. A provided colliding code raises `ValueError(f"[크롤] {row}행 판매자관리코드 중복: {code}")`. New listing gets `sale_name=name`, `market_price`, `margin_rate` (row value or CLI `margin`), unit fields, `active=1`.
- Existing qty-1 listing updates only `market_price` and `updated_at`; preserve every other listing field.
- Insert one `price_history` row per imported listing with `product_id`, `listing_id`, `price`, `observed_at`, `batch_id`, `crawl_path`.
- Update the batch counts and commit. Count `inserted`/`updated` per product upsert; `skipped` from `CrawlData.skipped`; `row_count = len(crawl.rows)`.
- Validate `category_code` is non-empty and `0 <= margin < 1` before writing; raise `ValueError` otherwise.

- [ ] **Step 4: Run tests to verify they pass**

Run the same `ImportTests` command. Expected: all pass.

- [ ] **Step 5: Test checkpoint**

Run the full suite. Expected: all existing and new tests pass.

---

### Task 3: Setting writer from DB rows

**Files:**
- Modify: `playauto/db.py`
- Create: `playauto/db_export.py`
- Create: `tests/test_db_export.py`

**Interfaces:**
- Consumes: `build_setting_headers()` from `playauto.constants`; `openpyxl.load_workbook`; `ExportRow` defined in `playauto/db.py`.
- Produces:
  - `ExportRow` in `playauto/db.py`, frozen dataclass with fields: `listing_id: int`, `product_id: int`, `source_seq: int`, `seller_code: str`, `sale_name: str`, `market_price: int`, `margin_rate: float`, `image_url: str`, `order_url: str`, `category_code: str`, `detail: str | None`, `keywords: str | None`, `manufacturer: str | None`, `brand: str | None`, `model: str | None`, `unit_price_visible: str | None`, `display_capacity: str | None`, `display_unit: str | None`, `pack_config: str | None`, `capacity_per_unit: str | None`, `bundle_qty: int`
  - `write_setting_from_rows(reference_path: str | Path, rows: list[ExportRow], output_path: str | Path) -> Path` in `playauto/db_export.py`

- [ ] **Step 1: Write the failing writer tests**

Create `tests/test_db_export.py` with helpers and tests:

```python
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from playauto.constants import build_setting_headers
from playauto.db import ExportRow
from playauto.db_export import write_setting_from_rows


def make_reference(path):
    wb = Workbook()
    setting = wb.active
    setting.title = "setting"
    setting.append(["old"])
    setting.append(["old-row"])
    template = wb.create_sheet("template")
    template.append([
        "쇼핑몰", "계정", "템플릿코드정보", "템플릿코드",
        "머리말/꼬리말 템플릿코드", "단일/일반",
    ])
    template.append(["SmartStore", "A", "1박스", "111", "900", "일반"])
    template.append(["Gmarket", "B", "1박스", "222", "900", "일반"])
    template.append(["SmartStore", "A", "1박스", "333", "901", "단일"])
    template["A1"].font = Font(bold=True)
    sheet1 = wb.create_sheet("Sheet1")
    sheet1["A1"] = "보조"
    wb.save(path)


def make_export_row(**overrides):
    values = dict(
        listing_id=1, product_id=1, source_seq=1, seller_code="MJ-0001",
        sale_name="상품1", market_price=7080, margin_rate=0.15,
        image_url="https://img/1.jpg", order_url="https://order/1",
        category_code="C1", detail="상세", keywords="kw", manufacturer="제조",
        brand="브랜드", model="모델", unit_price_visible="Y",
        display_capacity="500", display_unit="ml", pack_config="묶음",
        capacity_per_unit="250", bundle_qty=1,
    )
    values.update(overrides)
    return ExportRow(**values)


class SettingWriterTests(unittest.TestCase):
    def test_write_setting_writes_headers_values_and_order_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.xlsx"
            output = tmp / "out" / "setting.xlsx"
            make_reference(reference)

            result = write_setting_from_rows(reference, [make_export_row()], output)
            ws = load_workbook(result)["setting"]
            headers = [cell.value for cell in ws[1]]
            row = [cell.value for cell in ws[2]]

        self.assertEqual(len(headers), 18)
        self.assertEqual(headers, [*build_setting_headers()[:-1], "주문링크"])
        self.assertEqual(
            row,
            [
                "C1", "1박스", "MJ-0001", "상품1", 7080, 0.15,
                "https://img/1.jpg", "상세", "kw", "제조", "브랜드", "모델",
                "Y", "500", "ml", "250", "묶음", "https://order/1",
            ],
        )

    def test_write_setting_preserves_template_and_other_sheets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.xlsx"
            output = tmp / "setting.xlsx"
            make_reference(reference)
            before_wb = load_workbook(reference)
            before = [
                [cell.value for cell in row]
                for row in before_wb["template"].iter_rows()
            ]

            result = write_setting_from_rows(reference, [make_export_row()], output)
            after_wb = load_workbook(result)
            after = [
                [cell.value for cell in row]
                for row in after_wb["template"].iter_rows()
            ]

        self.assertEqual(after, before)
        self.assertTrue(after_wb["template"]["A1"].font.bold)
        self.assertEqual(after_wb["Sheet1"]["A1"].value, "보조")

    def test_write_setting_rejects_missing_sheets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.xlsx"
            wb = Workbook()
            wb.active.title = "setting"
            wb.save(reference)
            with self.assertRaisesRegex(ValueError, "template"):
                write_setting_from_rows(reference, [], tmp / "setting.xlsx")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
& 'C:\Users\kjhch\AppData\Local\Temp\py312\py\python.exe' -m unittest tests.test_db_export.SettingWriterTests -v
```

Expected: import error for `playauto.db_export`.

- [ ] **Step 3: Implement `ExportRow` and `write_setting_from_rows`**

Rules:
- Define `ExportRow` in `playauto/db.py`; `db_export.py` imports it.
- Load the reference with `load_workbook(reference_path)` (not `data_only`).
- Require `setting` and `template`; raise `ValueError(f"필수 시트 누락: {missing}")` matching the existing style.
- Clear the `setting` sheet, then append `[*build_setting_headers()[:-1], "주문링크"]`.
- Append one row per `ExportRow` in the exact order shown by the test.
- Create `output_path.parent` and save to `output_path`; return `Path(output_path)`.
- Do not read or modify `template` or any other sheet.

- [ ] **Step 4: Run tests to verify they pass**

Run the same writer test command. Expected: all pass.

- [ ] **Step 5: Test checkpoint**

Run the full suite. Expected: all pass.

---

### Task 4: Export query, validation, and full DB export

**Files:**
- Modify: `playauto/db.py`
- Modify: `playauto/db_export.py`
- Modify: `tests/test_db_export.py`

**Interfaces:**
- Consumes: `connect`, `ensure_schema`, `CrawlData`, `CrawlRow`, `import_crawl`; `write_setting_from_rows`; `convert_phase1`, `setting_copy_path`, `output_paths`.
- Produces:
  - `fetch_export_rows(conn) -> list[ExportRow]` and `validate_export_rows(rows: list[ExportRow]) -> None` in `playauto/db.py`
  - `export_from_db(db_path, reference_path, output_dir, selected_option, coupang_single=False, commission=None, run_date=None) -> dict` in `playauto/db_export.py`

- [ ] **Step 1: Write the failing export tests**

Append to `tests/test_db_export.py`:

```python
from datetime import date

from playauto.db import (
    CrawlData, CrawlRow, connect, ensure_schema, fetch_export_rows, import_crawl,
    validate_export_rows,
)
from playauto.db_export import export_from_db
from playauto.xlsx import output_paths, setting_copy_path


def make_db(path):
    conn = connect(path)
    ensure_schema(conn)
    return conn


class ExportTests(unittest.TestCase):
    def test_fetch_export_rows_orders_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = make_db(Path(tmp) / "test.db")
            import_crawl(
                conn,
                CrawlData((
                    CrawlRow(2, "B", 7080, "https://img/b.jpg", "https://order/b"),
                    CrawlRow(1, "A", 7080, "https://img/a.jpg", "https://order/a"),
                ), 0),
                category_code="C1", margin=0.15, crawl_path="crawl.xlsx",
            )
            ids = {
                row["order_url"]: row["id"]
                for row in conn.execute("SELECT id, order_url FROM products")
            }
            conn.execute(
                "INSERT INTO listings (product_id, seller_code, bundle_qty, sale_name, "
                "market_price, margin_rate, active, created_at, updated_at) "
                "VALUES (?, 'B-2', 2, 'B2', 14160, 0.15, 1, 'now', 'now')",
                (ids["https://order/b"],),
            )
            conn.execute(
                "INSERT INTO listings (product_id, seller_code, bundle_qty, sale_name, "
                "market_price, margin_rate, active, created_at, updated_at) "
                "VALUES (?, 'A-2', 2, 'A2', 14160, 0.15, 0, 'now', 'now')",
                (ids["https://order/a"],),
            )
            conn.commit()

            rows = fetch_export_rows(conn)
            conn.close()

        self.assertEqual(
            [(row.source_seq, row.bundle_qty, row.seller_code) for row in rows],
            [(1, 1, "MJ-0001"), (2, 1, "MJ-0002"), (2, 2, "B-2")],
        )

    def test_validate_export_rows_rejects_blank_order_url(self):
        with self.assertRaisesRegex(ValueError, "order_url"):
            validate_export_rows([make_export_row(order_url="")])

    def test_validate_export_rows_rejects_margin_out_of_range(self):
        with self.assertRaisesRegex(ValueError, "margin_rate"):
            validate_export_rows([make_export_row(margin_rate=1.0)])

    def test_export_includes_user_bundle_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "test.db"
            reference = tmp / "reference.xlsx"
            out = tmp / "out"
            make_reference(reference)
            conn = make_db(db)
            import_crawl(
                conn,
                CrawlData((CrawlRow(1, "상품1", 7080, "https://img/1.jpg", "https://order/1"),), 0),
                category_code="C1", margin=0.15, crawl_path="crawl.xlsx",
            )
            product_id = conn.execute("SELECT id FROM products").fetchone()[0]
            conn.execute(
                "INSERT INTO listings (product_id, seller_code, bundle_qty, sale_name, "
                "market_price, margin_rate, active, created_at, updated_at) "
                "VALUES (?, 'MJ-0001-2', 2, '2개묶음', 14160, 0.15, 1, 'now', 'now')",
                (product_id,),
            )
            conn.commit()
            conn.close()

            result = export_from_db(
                db, reference, out, selected_option="기타재화[35]",
                run_date=date(2026, 10, 27),
            )
            ws = load_workbook(result["setting"])["setting"]

        self.assertEqual(ws.max_row, 3)
        self.assertEqual(ws["C3"].value, "MJ-0001-2")
        self.assertEqual(ws["D3"].value, "2개묶음")
        self.assertEqual(ws["E3"].value, 14160)

    def test_export_from_db_creates_setting_and_finals(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "test.db"
            reference = tmp / "reference.xlsx"
            out = tmp / "out"
            make_reference(reference)
            conn = make_db(db)
            import_crawl(
                conn,
                CrawlData((CrawlRow(1, "상품1", 7080, "https://img/1.jpg", "https://order/1"),), 0),
                category_code="C1", margin=0.15, crawl_path="crawl.xlsx",
            )
            conn.commit()
            conn.close()

            result = export_from_db(
                db, reference, out, selected_option="기타재화[35]",
                commission={"지마켓": 12.0, "스마트스토어": 6.0, "쿠팡": 10.0},
                run_date=date(2026, 10, 27),
            )
            setting_ws = load_workbook(result["setting"])["setting"]
            single_ws = load_workbook(result["single"]).active
            general_ws = load_workbook(result["general"]).active
            single_headers = [cell.value for cell in single_ws[1]]
            general_headers = [cell.value for cell in general_ws[1]]
            single_price = single_ws.cell(
                row=2, column=single_headers.index("판매가") + 1
            ).value
            general_price = general_ws.cell(
                row=2, column=general_headers.index("판매가") + 1
            ).value

        self.assertEqual(setting_ws["R2"].value, "https://order/1")
        self.assertNotIn("주문링크", single_headers)
        self.assertNotIn("주문링크", general_headers)
        self.assertEqual(single_price, 9500)
        self.assertEqual(general_price, 8900)

    def test_export_from_db_fails_before_writing_when_row_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "test.db"
            reference = tmp / "reference.xlsx"
            out = tmp / "out"
            make_reference(reference)
            conn = make_db(db)
            import_crawl(
                conn,
                CrawlData((CrawlRow(1, "상품1", 7080, "https://img/1.jpg", "https://order/1"),), 0),
                category_code="C1", margin=0.15, crawl_path="crawl.xlsx",
            )
            conn.execute("UPDATE products SET order_url=''")
            conn.commit()
            conn.close()

            with self.assertRaisesRegex(ValueError, "order_url"):
                export_from_db(
                    db, reference, out, selected_option="기타재화[35]",
                    run_date=date(2026, 10, 27),
                )
            self.assertFalse(setting_copy_path(out, date(2026, 10, 27)).exists())
            self.assertFalse(output_paths(out, date(2026, 10, 27), False)[0].exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
& 'C:\Users\kjhch\AppData\Local\Temp\py312\py\python.exe' -m unittest tests.test_db_export.ExportTests -v
```

Expected: import error for `fetch_export_rows`/`export_from_db`.

- [ ] **Step 3: Implement export query, validation, and orchestration**

Rules:
- Add `fetch_export_rows` and `validate_export_rows` to `playauto/db.py`; add `export_from_db` to `playauto/db_export.py`.
- `fetch_export_rows` uses:

```sql
SELECT l.id AS listing_id, p.id AS product_id, p.source_seq, l.seller_code,
       l.sale_name, l.market_price, l.margin_rate, p.image_url, p.order_url,
       p.category_code, p.detail, p.keywords, p.manufacturer, p.brand, p.model,
       l.unit_price_visible, l.display_capacity, l.display_unit, l.pack_config,
       l.capacity_per_unit, l.bundle_qty
FROM listings l JOIN products p ON p.id = l.product_id
WHERE l.active = 1
ORDER BY p.source_seq, l.bundle_qty, l.id
```

Map each row to `ExportRow`.
- `validate_export_rows` raises `ValueError` if the list is empty or any required text is blank: `seller_code`, `sale_name`, `image_url`, `order_url`, `category_code`. It also rejects `margin_rate` outside `[0, 1)` and non-positive `market_price`; include listing id in the message.
- `export_from_db`: connect, `ensure_schema`, fetch, validate, then close the connection before writing (use `try/finally` so validation errors also close it). Compute `run_date = run_date or date.today()`, write setting via `write_setting_from_rows` to `setting_copy_path(output_dir, run_date)`, then set `result = convert_phase1(setting_path, output_dir, selected_option, coupang_single, commission, run_date, copy_setting=False)`. Return `{"setting": setting_path, "single": result["single"], "general": result["general"]}`.
- Validation must happen before any file write.

- [ ] **Step 4: Run tests to verify they pass**

Run the same `ExportTests` command. Expected: all pass.

- [ ] **Step 5: Test checkpoint**

Run the full suite. Expected: all pass.

---

### Task 5: DB CLI and `run_converter.py` dispatch

**Files:**
- Create: `playauto/db_cli.py`
- Modify: `run_converter.py`
- Create: `tests/test_db_cli.py`

**Interfaces:**
- Consumes: `connect`, `ensure_schema`, `load_crawl_rows`, `import_crawl`; `export_from_db`.
- Produces:
  - `build_parser()` with subcommands `db-import` and `db-export`
  - `main(argv=None) -> int`
  - `run_converter.py` dispatches `db-import`/`db-export` to `playauto.db_cli.main`, otherwise to the existing `playauto.cli.main`.

- [ ] **Step 1: Write the failing CLI test**

Create `tests/test_db_cli.py`:

```python
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook

from playauto.db_cli import main as db_main
from tests.test_db import make_crawl
from tests.test_db_export import make_reference


class DbCliTests(unittest.TestCase):
    def test_import_then_edit_then_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "playauto.db"
            crawl = tmp / "crawl.xlsx"
            reference = tmp / "reference.xlsx"
            out = tmp / "out"
            make_crawl(
                crawl,
                rows=[[
                    1, "https://img/1.jpg", "상품1", "7,080원", "https://order/1",
                    None, None, None, None, None, None, None, None, None, None, None, None,
                ]],
            )
            make_reference(reference)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = db_main([
                    "db-import", "--db", str(db), "--crawl", str(crawl),
                    "--category-code", "기타재화[35]",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["inserted"], 1)

            conn = sqlite3.connect(db)
            conn.execute("UPDATE products SET category_code='가공식품[21]', detail='수정상세'")
            conn.execute("UPDATE listings SET margin_rate=0.2, sale_name='수정상품'")
            conn.commit()
            conn.close()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = db_main([
                    "db-export", "--db", str(db), "--reference", str(reference),
                    "--output-dir", str(out), "--date", "2026-10-27",
                ])
            result = json.loads(stdout.getvalue())
            setting = load_workbook(result["setting"])["setting"]
            single = load_workbook(result["single"]).active

            out_coupang = tmp / "out_coupang"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code_coupang = db_main([
                    "db-export", "--db", str(db), "--reference", str(reference),
                    "--output-dir", str(out_coupang), "--date", "2026-10-27",
                    "--coupang-single",
                ])
            result_coupang = json.loads(stdout.getvalue())
            coupang_ws = load_workbook(result_coupang["single"]).active

        self.assertEqual(code, 0)
        self.assertEqual(setting["A2"].value, "가공식품[21]")
        self.assertEqual(setting["D2"].value, "수정상품")
        self.assertEqual(setting["F2"].value, 0.2)
        self.assertEqual(setting["H2"].value, "수정상세")
        self.assertEqual(setting["R2"].value, "https://order/1")
        self.assertNotIn("주문링크", [cell.value for cell in single[1]])
        self.assertEqual(code_coupang, 0)
        self.assertTrue(Path(result_coupang["single"]).exists())
        self.assertIsNone(result_coupang["general"])
        self.assertNotIn("주문링크", [cell.value for cell in coupang_ws[1]])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
& 'C:\Users\kjhch\AppData\Local\Temp\py312\py\python.exe' -m unittest tests.test_db_cli -v
```

Expected: import error for `playauto.db_cli`.

- [ ] **Step 3: Implement `db_cli.py` and dispatch**

Rules:
- `build_parser` creates a top-level parser with subparsers. `db-import` requires `--crawl` and `--category-code`, defaults `--db data/playauto.db`, `--margin 0.15`. `db-export` requires `--reference`, defaults `--db data/playauto.db`, `--output-dir .`, `--option 기타재화[35]`, `--commission-gmarket 12.0`, `--commission-smartstore 6.0`, `--commission-coupang 10.0`, `--date` via `date.fromisoformat`, and `--coupang-single`.
- Do not add `--no-setting-copy` to `db-export`; DB export always creates its setting file.
- `db-import`: connect, ensure schema, load crawl, import, close the connection, print JSON with `db`, `batch_id`, `inserted`, `updated`, `skipped`; return 0.
- `db-export`: build commission dict, call `export_from_db`, print JSON with string paths; return 0.
- Both print with `ensure_ascii=True`; convert Path values to `str` and leave `None` as JSON null, matching the existing CLI.
- `run_converter.py`: after `sys.path` and stream setup, if `len(sys.argv) > 1` and `sys.argv[1]` is `db-import` or `db-export`, call `playauto.db_cli.main(sys.argv[1:])`; otherwise call the existing `playauto.cli.main()`.

- [ ] **Step 4: Run test to verify it passes**

Run the same `tests.test_db_cli` command. Expected: pass.

- [ ] **Step 5: Test checkpoint**

Run the full suite. Expected: all pass.

---

### Task 6: End-to-end verification

**Files:**
- No code changes expected.
- Verify: `run_converter.py`, `playauto/db.py`, `playauto/db_export.py`, `playauto/db_cli.py`.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified DB import/export behavior and unchanged direct CLI.

- [ ] **Step 1: Run the full test suite**

```powershell
& 'C:\Users\kjhch\AppData\Local\Temp\py312\py\python.exe' -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run DB import/export against the real reference workbook**

Run from the repository root `D:\Opencode\playauto_converter`. Create the temporary crawl, using the real `D:\Opencode\on\261009.xlsx` as `--reference`. Run:

```powershell
$tmpDir = 'C:\Users\kjhch\AppData\Local\Temp\opencode\playauto-e2e'
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
Remove-Item -LiteralPath "$tmpDir\playauto.db" -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "$tmpDir\out" -Recurse -Force -ErrorAction SilentlyContinue
& 'C:\Users\kjhch\AppData\Local\Temp\py312\py\python.exe' -c "import sys; sys.path[:0]=[r'D:\Opencode\playauto_converter\vendor', r'D:\Opencode\playauto_converter']; from openpyxl import Workbook; wb=Workbook(); ws=wb.active; ws.append(['순번','대표이미지','상품명','판매가격','URL']); ws.append([1,'https://img/1.jpg','테스트상품','7,080원','https://order/1']); wb.save(r'C:\Users\kjhch\AppData\Local\Temp\opencode\playauto-e2e\crawl.xlsx')"
& 'C:\Users\kjhch\AppData\Local\Temp\py312\py\python.exe' run_converter.py db-import --db "$tmpDir\playauto.db" --crawl "$tmpDir\crawl.xlsx" --category-code "기타재화[35]"
& 'C:\Users\kjhch\AppData\Local\Temp\py312\py\python.exe' run_converter.py db-export --db "$tmpDir\playauto.db" --reference "D:\Opencode\on\261009.xlsx" --output-dir "$tmpDir\out" --date 2026-10-27
```

Expected:
- DB import JSON reports 1 inserted.
- Output contains `2026-10-27_플레이오토_설정.xlsx`, `_단일.xlsx`, `_일반.xlsx`.
- Setting has one data row, `템플릿코드정보=1박스`, and a `주문링크` in column R.
- Final files have no `주문링크` header.

- [ ] **Step 3: Verify the real template sheet is unchanged**

Open the reference and exported setting with openpyxl and compare every cell value in `template`; compare the `template` header font/style of at least `A1`. Expected: equal.

- [ ] **Step 4: Verify the direct converter still works**

From the repository root, run:

```powershell
& 'C:\Users\kjhch\AppData\Local\Temp\py312\py\python.exe' run_converter.py "D:\Opencode\on\261009.xlsx" --output-dir "C:\Users\kjhch\AppData\Local\Temp\opencode\playauto-e2e\direct" --date 2026-10-27
```

Expected: `_설정.xlsx`, `_단일.xlsx`, and `_일반.xlsx` are created, and the final files have no `주문링크` header.

- [ ] **Step 5: Report results**

Report the test counts, the three generated paths, and any limitation found. Do not claim completion without the commands' observed output.
