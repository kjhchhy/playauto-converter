import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from playauto.db import connect, ensure_schema
from tests.web_helpers import (
    login,
    make_web_app,
    post_with_csrf,
    seed_product,
)


class DetailPageRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app, self.db_path = make_web_app(self.tmp.name)
        self.client = self.app.test_client()
        login(self.client)
        self.conn = connect(self.db_path)
        ensure_schema(self.conn)
        self.addCleanup(self.conn.close)
        self.pid, _ = seed_product(self.conn, name="상품1")

    def test_detail_tab_renders_detail_page_fields(self):
        response = self.client.get(f"/products/{self.pid}?tab=detail")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("상세페이지", body)
        self.assertIn("detail_page_title", body)
        self.assertIn("detail_page_url", body)

    def test_save_detail_page_route_persists_values(self):
        response = post_with_csrf(
            self.client,
            f"/products/{self.pid}/detail-page",
            {
                "detail_page_title": "새 제목",
                "detail_page_marketing": "새 문구",
                "detail_page_caution": "새 주의",
                "detail_page_extra_images": "https://img/1.jpg",
                "notice_image_url": "https://img/notice.jpg",
                "detail_page_url": "https://11st/url",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("tab=detail", response.headers["Location"])
        row = self.conn.execute(
            "SELECT * FROM products WHERE id = ?", (self.pid,)
        ).fetchone()
        self.assertEqual(row["detail_page_title"], "새 제목")
        self.assertEqual(
            json.loads(row["detail_page_extra_images"]), ["https://img/1.jpg"]
        )
        self.assertEqual(row["detail_page_url"], "https://11st/url")

    def test_generate_route_flashes_and_redirects(self):
        with patch("playauto.web.routes.generate_detail_page") as generate:
            generate.return_value = Path("data/detail-pages/1.jpg")
            response = post_with_csrf(
                self.client,
                f"/products/{self.pid}/detail-page/generate",
                {},
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("tab=detail", response.headers["Location"])
        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[1], self.pid)

    def test_generate_route_flashes_error_when_notice_image_missing(self):
        response = post_with_csrf(
            self.client,
            f"/products/{self.pid}/detail-page/generate",
            {},
        )
        page = self.client.get(response.headers["Location"])
        body = page.get_data(as_text=True)

        self.assertEqual(page.status_code, 200)
        self.assertIn("고시 이미지", body)

    def test_preview_returns_jpg_when_present(self):
        preview_dir = Path(self.tmp.name) / "detail-pages"
        preview_dir.mkdir()
        (preview_dir / f"{self.pid}.jpg").write_bytes(b"jpeg")

        with patch("playauto.web.routes.DETAIL_PAGE_DIR", preview_dir):
            response = self.client.get(
                f"/products/{self.pid}/detail-page/preview"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertEqual(response.data, b"jpeg")
        response.close()


if __name__ == "__main__":
    unittest.main()
