import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook, load_workbook

from playauto.db import connect, ensure_schema
from playauto.web.export_service import (
    delete_export,
    export_to_dir,
    list_exports,
    save_reference,
    validate_reference,
)
from tests.web_helpers import make_web_app, seed_product


def make_reference(path):
    wb = Workbook()
    setting = wb.active
    setting.title = "setting"
    setting.append(["old"])
    template = wb.create_sheet("template")
    template.append(
        [
            "쇼핑몰",
            "계정",
            "템플릿코드정보",
            "템플릿코드",
            "머리말/꼬리말 템플릿코드",
            "단일/일반",
        ]
    )
    template.append(["SmartStore", "A", "1박스", "111", "900", "일반"])
    wb.save(path)


class ExportServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reference = self.root / "current.xlsx"
        make_reference(self.reference)
        self.app, self.db_path = make_web_app(self.tmp.name)
        conn = connect(self.db_path)
        ensure_schema(conn)
        seed_product(conn)
        conn.close()

    def test_validate_reference(self):
        validate_reference(self.reference)
        bad = self.root / "bad.xlsx"
        wb = Workbook()
        wb.active.title = "setting"
        wb.save(bad)
        with self.assertRaises(ValueError):
            validate_reference(bad)

    def test_save_reference_replaces_and_hashes(self):
        src = self.root / "upload.xlsx"
        make_reference(src)
        dest = self.root / "stored" / "current.xlsx"
        info = save_reference(src, dest)
        self.assertTrue(dest.exists())
        self.assertEqual(
            info["sha256"],
            hashlib.sha256(dest.read_bytes()).hexdigest(),
        )

    def test_export_creates_files_and_list_delete(self):
        result = export_to_dir(
            self.db_path,
            self.reference,
            self.root / "exports",
            option="기타재화[35]",
            run_date=None,
            coupang_single=False,
        )
        self.assertTrue(result.setting.exists())
        self.assertTrue(result.single.exists())
        self.assertTrue(result.general.exists())
        wb = load_workbook(result.setting)
        self.assertIn("주문링크", [c.value for c in wb["setting"][1]])
        exports = list_exports(self.root / "exports")
        self.assertEqual(len(exports), 1)
        self.assertTrue(delete_export(self.root / "exports", result.export_id))
        self.assertFalse(result.directory.exists())

    def test_export_missing_reference_raises(self):
        with self.assertRaises(ValueError):
            export_to_dir(
                self.db_path,
                self.root / "missing.xlsx",
                self.root / "exports",
                option="기타재화[35]",
            )
