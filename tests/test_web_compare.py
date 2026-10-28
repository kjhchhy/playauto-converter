import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from playauto.db import connect, ensure_schema
from playauto.web.queries import (
    create_crawl_job,
    ensure_default_settings,
    set_setting,
)
from tests.web_helpers import (
    login,
    make_web_app,
    post_with_csrf,
    seed_product,
)


class CompareAndSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app, self.db_path = make_web_app(self.tmp.name)
        self.client = self.app.test_client()
        login(self.client)
        self.conn = connect(self.db_path)
        ensure_schema(self.conn)
        self.addCleanup(self.conn.close)
        seed_product(self.conn, seq=1, name="카프리썬", price=25530)
        self.conn.execute(
            "UPDATE listings SET capacity_per_unit='200ml'"
        )
        self.conn.commit()

    def test_compare_shows_unit_price_and_sale_price(self):
        response = self.client.get("/compare")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("12,765", body)
        self.assertIn("100ml", body)
        self.assertIn("12,765 / 100ml", body)
        self.assertNotIn("12,765100ml", body)
        self.assertIn("34,200", body)

    def test_settings_update_persists(self):
        response = post_with_csrf(
            self.client,
            "/settings",
            {"default_margin": "0.2", "default_category_code": "가공식품[21]"},
        )
        self.assertEqual(response.status_code, 302)
        rows = dict(
            self.conn.execute("SELECT key, value FROM app_settings").fetchall()
        )
        self.assertEqual(rows["default_margin"], "0.2")
        self.assertEqual(rows["default_category_code"], "가공식품[21]")

    def test_dashboard_shows_counts(self):
        response = self.client.get("/")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("활성 상품", body)
        self.assertIn("1", body)

    def test_settings_invalid_margin_rejected(self):
        response = post_with_csrf(
            self.client,
            "/settings",
            {"default_margin": "1.5", "default_category_code": "가공식품[21]"},
        )
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("마진율", body)
        rows = dict(
            self.conn.execute("SELECT key, value FROM app_settings").fetchall()
        )
        self.assertNotEqual(rows.get("default_margin"), "1.5")

    def test_settings_margin_one_rejected(self):
        response = post_with_csrf(
            self.client,
            "/settings",
            {"default_margin": "1.0", "default_category_code": "가공식품[21]"},
        )
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("마진율", body)
        rows = dict(
            self.conn.execute("SELECT key, value FROM app_settings").fetchall()
        )
        self.assertNotEqual(rows.get("default_margin"), "1.0")

    def test_settings_invalid_category_rejected(self):
        response = post_with_csrf(
            self.client,
            "/settings",
            {"default_margin": "0.15", "default_category_code": "없는분류[99]"},
        )
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("상품분류", body)

    def test_settings_requires_csrf(self):
        response = self.client.post(
            "/settings",
            data={"default_margin": "0.2", "default_category_code": "가공식품[21]"},
        )
        self.assertEqual(response.status_code, 400)

    def test_compare_invalid_sort_falls_back_safely(self):
        response = self.client.get("/compare", query_string={"sort": "evil; DROP"})
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("카프리썬", body)

    def test_ensure_default_settings_preserves_existing_values(self):
        set_setting(self.conn, "default_margin", "0.3")
        ensure_default_settings(self.conn)
        rows = dict(
            self.conn.execute("SELECT key, value FROM app_settings").fetchall()
        )
        self.assertEqual(rows["default_margin"], "0.3")
        self.assertEqual(rows["commission_gmarket"], "12.0")
        self.assertEqual(rows["default_category_code"], "기타재화[35]")

    def test_dashboard_shows_recent_job_count(self):
        create_crawl_job(
            self.conn,
            source="search",
            search_url="https://www.gmarket.co.kr/n/stardelivery/search?keyword=x",
            category_code="기타재화[35]",
            margin=0.15,
        )
        response = self.client.get("/")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("활성 listing", body)
        self.assertIn("최근 작업 1건", body)

    def test_dashboard_renders_korean_job_labels(self):
        job_id = create_crawl_job(
            self.conn,
            source="search",
            search_url="https://www.gmarket.co.kr/n/stardelivery/search?keyword=x",
            category_code="기타재화[35]",
            margin=0.15,
        )
        self.conn.execute(
            "UPDATE crawl_jobs SET status = 'succeeded' WHERE id = ?",
            (job_id,),
        )
        self.conn.commit()
        response = self.client.get("/")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("완료", body)
        self.assertIn("검색", body)
        self.assertNotIn("succeeded", body)
        self.assertNotIn("search", body)


if __name__ == "__main__":
    unittest.main()
