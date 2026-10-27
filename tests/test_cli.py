import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from playauto.cli import main
from tests.test_xlsx import make_input


class CliTests(unittest.TestCase):
    def test_cli_creates_setting_and_final_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = tmp / "input.xlsx"
            make_input(path)
            out = tmp / "out"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        str(path),
                        "--output-dir",
                        str(out),
                        "--date",
                        "2026-10-27",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue((out / "2026-10-27_플레이오토_설정.xlsx").exists())
            self.assertTrue((out / "2026-10-27_플레이오토_단일.xlsx").exists())
            self.assertTrue((out / "2026-10-27_플레이오토_일반.xlsx").exists())
            self.assertIn("플레이오토_단일", json.loads(stdout.getvalue())["single"])

    def test_cli_coupang_creates_only_coupang_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = tmp / "input.xlsx"
            make_input(path)
            out = tmp / "out"

            with redirect_stdout(io.StringIO()):
                code = main(
                    [
                        str(path),
                        "--output-dir",
                        str(out),
                        "--date",
                        "2026-10-27",
                        "--coupang-single",
                        "--no-setting-copy",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue((out / "2026-10-27_플레이오토_쿠팡.xlsx").exists())
            self.assertFalse((out / "2026-10-27_플레이오토_단일.xlsx").exists())
            self.assertFalse((out / "2026-10-27_플레이오토_설정.xlsx").exists())


if __name__ == "__main__":
    unittest.main()
