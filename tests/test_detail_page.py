import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from playauto.detail_page import (
    DEFAULT_CAUTION_TEXT,
    PALETTES,
    build_detail_page_html,
    pick_palette,
    title_font_size,
)


class DetailPageHtmlTests(unittest.TestCase):
    def test_build_detail_page_html_escapes_user_text_and_orders_images(self):
        html = build_detail_page_html(
            title="<script>alert(1)</script>",
            marketing="<b>신선한</b> 주스",
            caution="<i>유통기한</i>을 확인하세요",
            main_image_url="https://img/main.jpg",
            extra_image_urls=["https://img/1.jpg", "https://img/2.jpg"],
            notice_image_url="https://img/notice.jpg",
            palette=PALETTES[0],
        )

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;b&gt;신선한&lt;/b&gt; 주스", html)
        self.assertNotIn("<b>신선한</b> 주스", html)
        self.assertIn("&lt;i&gt;유통기한&lt;/i&gt;을 확인하세요", html)
        self.assertNotIn("<i>유통기한</i>을 확인하세요", html)
        self.assertLess(
            html.index("https://img/main.jpg"), html.index("https://img/1.jpg")
        )
        self.assertLess(
            html.index("https://img/2.jpg"), html.index("https://img/notice.jpg")
        )
        self.assertIn("width: 860px", html)
        self.assertIn("-webkit-line-clamp: 2", html)
        self.assertIn("word-break: keep-all", html)

    def test_build_detail_page_html_uses_default_caution_when_blank(self):
        html = build_detail_page_html(
            title="제목",
            marketing="문구",
            caution="",
            main_image_url="https://img/main.jpg",
            extra_image_urls=[],
            notice_image_url="https://img/notice.jpg",
            palette=PALETTES[0],
        )

        self.assertIn(DEFAULT_CAUTION_TEXT, html)

    def test_title_font_size_shrinks_for_long_titles(self):
        self.assertEqual(title_font_size("짧은 제목"), 48)
        self.assertEqual(title_font_size("가" * 40), 36)
        self.assertEqual(title_font_size("가" * 60), 30)

    def test_pick_palette_is_deterministic_with_seed(self):
        self.assertEqual(pick_palette(seed=0), pick_palette(seed=0))


if __name__ == "__main__":
    unittest.main()
