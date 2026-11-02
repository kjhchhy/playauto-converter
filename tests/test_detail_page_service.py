import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from playauto.web.detail_page_service import (
    generate_detail_page,
    parse_detail_page_form,
    save_detail_page,
)
from tests.web_helpers import new_conn, seed_product


class DetailPageServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = new_conn(self.tmp.name)
        self.addCleanup(self.conn.close)
        self.pid, _ = seed_product(self.conn, name="상품1")
        self.output_dir = Path(self.tmp.name) / "detail-pages"

    def test_parse_detail_page_form_caps_extra_images_at_five(self):
        values = parse_detail_page_form(
            {
                "detail_page_title": "제목",
                "detail_page_marketing": "문구",
                "detail_page_caution": "주의",
                "detail_page_extra_images": "a\nb\nc\nd\ne\nf",
                "notice_image_url": "https://img/notice.jpg",
                "detail_page_url": "https://11st/url",
            }
        )

        self.assertEqual(
            values["detail_page_extra_images"], ["a", "b", "c", "d", "e"]
        )
        self.assertEqual(values["detail_page_title"], "제목")

    def test_save_detail_page_persists_fields_and_serializes_images(self):
        save_detail_page(
            self.conn,
            self.pid,
            {
                "detail_page_title": "새 제목",
                "detail_page_marketing": "새 문구",
                "detail_page_caution": "새 주의",
                "detail_page_extra_images": ["https://img/1.jpg"],
                "notice_image_url": "https://img/notice.jpg",
                "detail_page_url": "https://11st/url",
            },
        )

        row = self.conn.execute(
            "SELECT * FROM products WHERE id = ?", (self.pid,)
        ).fetchone()
        self.assertEqual(row["detail_page_title"], "새 제목")
        self.assertEqual(
            json.loads(row["detail_page_extra_images"]), ["https://img/1.jpg"]
        )
        self.assertEqual(row["detail_page_url"], "https://11st/url")
        self.assertIsNotNone(row["detail_page_updated_at"])

    def test_generate_detail_page_requires_notice_image(self):
        with self.assertRaisesRegex(ValueError, "고시 이미지"):
            generate_detail_page(
                self.conn, self.pid, output_dir=self.output_dir
            )

    def test_generate_detail_page_uses_renderer_and_returns_path(self):
        self.conn.execute(
            "UPDATE products SET notice_image_url = ?, "
            "detail_page_marketing = ?, detail_page_caution = ?, "
            "detail_page_extra_images = ? WHERE id = ?",
            (
                "https://img/notice.jpg",
                "문구",
                "주의",
                json.dumps(["https://img/1.jpg"]),
                self.pid,
            ),
        )
        self.conn.commit()
        seen = {}

        def fake_renderer(html, output_path):
            seen["html"] = html
            output_path.write_bytes(b"jpeg")
            return output_path

        path = generate_detail_page(
            self.conn,
            self.pid,
            renderer=fake_renderer,
            palette_seed=0,
            output_dir=self.output_dir,
        )

        self.assertEqual(path, self.output_dir / f"{self.pid}.jpg")
        self.assertIn("상품1", seen["html"])
        self.assertIn("https://img/1.jpg", seen["html"])
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
