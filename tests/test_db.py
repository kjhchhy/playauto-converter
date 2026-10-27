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
