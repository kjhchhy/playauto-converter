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
    def test_schema_rejects_null_required_product_and_listing_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "test.db")
            try:
                ensure_schema(conn)
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "INSERT INTO products (source_seq, name, image_url, "
                        "order_url, category_code, last_seen_at) "
                        "VALUES (1, 'name', 'img', 'https://order/1', NULL, 'now')"
                    )
                product_id = conn.execute(
                    "INSERT INTO products (source_seq, name, image_url, "
                    "order_url, category_code, last_seen_at) "
                    "VALUES (1, 'name', 'img', 'https://order/2', 'CAT', 'now')"
                ).lastrowid
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "INSERT INTO listings (product_id, seller_code, "
                        "sale_name, market_price) "
                        "VALUES (?, 'S1', NULL, 1000)",
                        (product_id,),
                    )
            finally:
                conn.close()

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

    def test_load_crawl_rows_allows_blank_optional_margin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crawl.xlsx"
            make_crawl(
                path,
                rows=[
                    [1, "img", "상품1", 1000, "https://order/1", "MJ-X", None],
                    [2, "img", "상품2", 2000, "https://order/2", "MJ-Y", ""],
                ],
            )
            data = load_crawl_rows(path)

        self.assertEqual(len(data.rows), 2)
        for row in data.rows:
            self.assertIsNone(row.margin_rate)

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
