import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from playauto.web.detail_page_image import render_html_to_jpeg


class DetailPageImageTests(unittest.TestCase):
    def test_render_html_to_jpeg_uses_fixed_jpeg_settings(self):
        calls = {}

        class FakePage:
            def set_viewport_size(self, size):
                calls["viewport"] = size

            def set_content(self, html, **kwargs):
                calls["content"] = (html, kwargs)

            def screenshot(self, **kwargs):
                calls["screenshot"] = kwargs

        class FakeBrowser:
            def new_page(self):
                return FakePage()

            def close(self):
                calls["closed"] = True

        class FakeChromium:
            def launch(self, headless):
                calls["headless"] = headless
                return FakeBrowser()

        class FakePlaywright:
            chromium = FakeChromium()

        class FakeCM:
            def __enter__(self):
                return FakePlaywright()

            def __exit__(self, *args):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "playauto.web.detail_page_image.sync_playwright",
                return_value=FakeCM(),
            ):
                output = render_html_to_jpeg("<html></html>", Path(tmp) / "out.jpg")
            self.assertEqual(output, Path(tmp) / "out.jpg")

        self.assertEqual(calls["viewport"], {"width": 860, "height": 1000})
        self.assertEqual(
            calls["content"][1], {"wait_until": "load", "timeout": 15000}
        )
        self.assertEqual(calls["screenshot"]["type"], "jpeg")
        self.assertEqual(calls["screenshot"]["quality"], 90)
        self.assertTrue(calls["screenshot"]["full_page"])
        self.assertTrue(calls["closed"])


if __name__ == "__main__":
    unittest.main()
