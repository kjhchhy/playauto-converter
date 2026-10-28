import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from playauto.db import SCHEMA_VERSION, connect, delete_product, ensure_schema


class WebSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = connect(Path(self.tmp.name) / "test.db")
        self.addCleanup(self.conn.close)
        ensure_schema(self.conn)

    def test_schema_v2_adds_web_tables_and_version(self):
        tables = {
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("app_settings", tables)
        self.assertIn("crawl_jobs", tables)
        self.assertEqual(SCHEMA_VERSION, 2)
        self.assertEqual(
            self.conn.execute("PRAGMA user_version").fetchone()[0], 2
        )

    def test_delete_product_removes_listings_and_history(self):
        from tests.web_helpers import seed_product

        product_id, listing_id = seed_product(self.conn)
        other_id, _ = seed_product(
            self.conn,
            seq=2,
            name="다른 상품",
            seller_code="MJ-0002",
            order_url="https://item.gmarket.co.kr/Item?goodscode=2",
        )

        deleted = delete_product(self.conn, product_id)

        self.assertEqual(deleted, 1)
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM products WHERE id=?", (product_id,)
            ).fetchone()
        )
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM listings WHERE id=?", (listing_id,)
            ).fetchone()
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM price_history WHERE product_id=?",
                (product_id,),
            ).fetchone()[0],
            0,
        )
        self.assertIsNotNone(
            self.conn.execute(
                "SELECT 1 FROM products WHERE id=?", (other_id,)
            ).fetchone()
        )

    def test_delete_product_missing_returns_zero(self):
        self.assertEqual(delete_product(self.conn, 9999), 0)
