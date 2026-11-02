import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from playauto.db import connect, ensure_schema
from playauto.web.queries import list_products
from tests.web_helpers import (
    login,
    make_web_app,
    post_with_csrf,
    seed_product,
)


class ProductRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app, self.db_path = make_web_app(self.tmp.name)
        self.client = self.app.test_client()
        login(self.client)
        self.conn = connect(self.db_path)
        ensure_schema(self.conn)
        self.addCleanup(self.conn.close)
        self.pid1, self.lid1 = seed_product(
            self.conn, seq=1, name="카프리썬", brand="농심", price=25530
        )
        self.pid2, self.lid2 = seed_product(
            self.conn,
            seq=2,
            name="다른 상품",
            brand="ABC",
            price=1000,
            seller_code="MJ-0002",
        )

    def test_product_list_filters_by_name(self):
        response = self.client.get("/products?q=카프리썬")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("카프리썬", body)
        self.assertNotIn("다른 상품", body)

    def test_product_detail_shows_price_history(self):
        response = self.client.get(f"/products/{self.pid1}")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("가격 이력", body)
        self.assertIn("25,530", body)

    def test_update_listing_margin_and_product_brand(self):
        response = post_with_csrf(
            self.client,
            f"/products/{self.pid1}",
            {
                "sale_name": "카프리썬",
                "margin_rate": "0.25",
                "brand": "농심_new",
                "manufacturer": "농심",
                "model": "CAPRI-40",
            },
        )
        self.assertEqual(response.status_code, 302)
        listing = self.conn.execute(
            "SELECT margin_rate FROM listings WHERE id=?", (self.lid1,)
        ).fetchone()
        product = self.conn.execute(
            "SELECT brand, manufacturer, model FROM products WHERE id=?",
            (self.pid1,),
        ).fetchone()
        self.assertAlmostEqual(listing["margin_rate"], 0.25)
        self.assertEqual(product["brand"], "농심_new")
        self.assertEqual(product["manufacturer"], "농심")
        self.assertEqual(product["model"], "CAPRI-40")

    def test_delete_removes_only_selected_product(self):
        response = post_with_csrf(
            self.client, f"/products/{self.pid1}/delete", {}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM products WHERE id=?", (self.pid1,)
            ).fetchone()
        )
        self.assertIsNotNone(
            self.conn.execute(
                "SELECT 1 FROM products WHERE id=?", (self.pid2,)
            ).fetchone()
        )

    def test_bulk_delete(self):
        response = post_with_csrf(
            self.client,
            "/products/delete",
            {"ids": [str(self.pid1), str(self.pid2)]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            0,
        )

    def test_query_helper_returns_count(self):
        rows, total = list_products(self.conn, q="카프리썬")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["name"], "카프리썬")
