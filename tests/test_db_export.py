import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from playauto.constants import build_setting_headers
from playauto.db import ExportRow
from playauto.db_export import write_setting_from_rows


def make_reference(path):
    wb = Workbook()
    setting = wb.active
    setting.title = "setting"
    setting.append(["old"])
    setting.append(["old-row"])
    template = wb.create_sheet("template")
    template.append([
        "쇼핑몰", "계정", "템플릿코드정보", "템플릿코드",
        "머리말/꼬리말 템플릿코드", "단일/일반",
    ])
    template.append(["SmartStore", "A", "1박스", "111", "900", "일반"])
    template.append(["Gmarket", "B", "1박스", "222", "900", "일반"])
    template.append(["SmartStore", "A", "1박스", "333", "901", "단일"])
    template["A1"].font = Font(bold=True)
    sheet1 = wb.create_sheet("Sheet1")
    sheet1["A1"] = "보조"
    wb.save(path)


def make_export_row(**overrides):
    values = dict(
        listing_id=1, product_id=1, source_seq=1, seller_code="MJ-0001",
        sale_name="상품1", market_price=7080, margin_rate=0.15,
        image_url="https://img/1.jpg", order_url="https://order/1",
        category_code="C1", detail="상세", keywords="kw", manufacturer="제조",
        brand="브랜드", model="모델", unit_price_visible="Y",
        display_capacity="500", display_unit="ml", pack_config="묶음",
        capacity_per_unit="250", bundle_qty=1,
    )
    values.update(overrides)
    return ExportRow(**values)


class SettingWriterTests(unittest.TestCase):
    def test_write_setting_writes_headers_values_and_order_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.xlsx"
            output = tmp / "out" / "setting.xlsx"
            make_reference(reference)

            result = write_setting_from_rows(reference, [make_export_row()], output)
            ws = load_workbook(result)["setting"]
            headers = [cell.value for cell in ws[1]]
            row = [cell.value for cell in ws[2]]

        self.assertEqual(len(headers), 18)
        self.assertEqual(headers, [*build_setting_headers()[:-1], "주문링크"])
        self.assertEqual(
            row,
            [
                "C1", "1박스", "MJ-0001", "상품1", 7080, 0.15,
                "https://img/1.jpg", "상세", "kw", "제조", "브랜드", "모델",
                "Y", "500", "ml", "250", "묶음", "https://order/1",
            ],
        )

    def test_write_setting_preserves_template_and_other_sheets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.xlsx"
            output = tmp / "setting.xlsx"
            make_reference(reference)
            before_wb = load_workbook(reference)
            before = [
                [cell.value for cell in row]
                for row in before_wb["template"].iter_rows()
            ]

            result = write_setting_from_rows(reference, [make_export_row()], output)
            after_wb = load_workbook(result)
            after = [
                [cell.value for cell in row]
                for row in after_wb["template"].iter_rows()
            ]

        self.assertEqual(after, before)
        self.assertTrue(after_wb["template"]["A1"].font.bold)
        self.assertEqual(after_wb["Sheet1"]["A1"].value, "보조")

    def test_write_setting_rejects_missing_sheets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.xlsx"
            wb = Workbook()
            wb.active.title = "setting"
            wb.save(reference)
            with self.assertRaisesRegex(ValueError, "template"):
                write_setting_from_rows(reference, [], tmp / "setting.xlsx")


from datetime import date

from playauto.db import (
    CrawlData, CrawlRow, connect, ensure_schema, fetch_export_rows, import_crawl,
    validate_export_rows,
)
from playauto.db_export import export_from_db
from playauto.xlsx import output_paths, setting_copy_path


def make_db(path):
    conn = connect(path)
    ensure_schema(conn)
    return conn


class ExportTests(unittest.TestCase):
    def test_fetch_export_rows_orders_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = make_db(Path(tmp) / "test.db")
            import_crawl(
                conn,
                CrawlData((
                    CrawlRow(2, "B", 7080, "https://img/b.jpg", "https://order/b"),
                    CrawlRow(1, "A", 7080, "https://img/a.jpg", "https://order/a"),
                ), 0),
                category_code="C1", margin=0.15, crawl_path="crawl.xlsx",
            )
            ids = {
                row["order_url"]: row["id"]
                for row in conn.execute("SELECT id, order_url FROM products")
            }
            conn.execute(
                "INSERT INTO listings (product_id, seller_code, bundle_qty, sale_name, "
                "market_price, margin_rate, active, created_at, updated_at) "
                "VALUES (?, 'B-2', 2, 'B2', 14160, 0.15, 1, 'now', 'now')",
                (ids["https://order/b"],),
            )
            conn.execute(
                "INSERT INTO listings (product_id, seller_code, bundle_qty, sale_name, "
                "market_price, margin_rate, active, created_at, updated_at) "
                "VALUES (?, 'A-2', 2, 'A2', 14160, 0.15, 0, 'now', 'now')",
                (ids["https://order/a"],),
            )
            conn.commit()

            rows = fetch_export_rows(conn)
            conn.close()

        self.assertEqual(
            [(row.source_seq, row.bundle_qty, row.seller_code) for row in rows],
            [(1, 1, "MJ-0001"), (2, 1, "MJ-0002"), (2, 2, "B-2")],
        )

    def test_validate_export_rows_rejects_blank_order_url(self):
        with self.assertRaisesRegex(ValueError, "order_url"):
            validate_export_rows([make_export_row(order_url="")])

    def test_validate_export_rows_rejects_margin_out_of_range(self):
        with self.assertRaisesRegex(ValueError, "margin_rate"):
            validate_export_rows([make_export_row(margin_rate=1.0)])

    def test_export_includes_user_bundle_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "test.db"
            reference = tmp / "reference.xlsx"
            out = tmp / "out"
            make_reference(reference)
            conn = make_db(db)
            import_crawl(
                conn,
                CrawlData((CrawlRow(1, "상품1", 7080, "https://img/1.jpg", "https://order/1"),), 0),
                category_code="C1", margin=0.15, crawl_path="crawl.xlsx",
            )
            product_id = conn.execute("SELECT id FROM products").fetchone()[0]
            conn.execute(
                "INSERT INTO listings (product_id, seller_code, bundle_qty, sale_name, "
                "market_price, margin_rate, active, created_at, updated_at) "
                "VALUES (?, 'MJ-0001-2', 2, '2개묶음', 14160, 0.15, 1, 'now', 'now')",
                (product_id,),
            )
            conn.commit()
            conn.close()

            result = export_from_db(
                db, reference, out, selected_option="기타재화[35]",
                run_date=date(2026, 10, 27),
            )
            ws = load_workbook(result["setting"])["setting"]

        self.assertEqual(ws.max_row, 3)
        self.assertEqual(ws["C3"].value, "MJ-0001-2")
        self.assertEqual(ws["D3"].value, "2개묶음")
        self.assertEqual(ws["E3"].value, 14160)

    def test_export_from_db_creates_setting_and_finals(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "test.db"
            reference = tmp / "reference.xlsx"
            out = tmp / "out"
            make_reference(reference)
            conn = make_db(db)
            import_crawl(
                conn,
                CrawlData((CrawlRow(1, "상품1", 7080, "https://img/1.jpg", "https://order/1"),), 0),
                category_code="C1", margin=0.15, crawl_path="crawl.xlsx",
            )
            conn.commit()
            conn.close()

            result = export_from_db(
                db, reference, out, selected_option="기타재화[35]",
                commission={"지마켓": 12.0, "스마트스토어": 6.0, "쿠팡": 10.0},
                run_date=date(2026, 10, 27),
            )
            setting_ws = load_workbook(result["setting"])["setting"]
            single_ws = load_workbook(result["single"]).active
            general_ws = load_workbook(result["general"]).active
            single_headers = [cell.value for cell in single_ws[1]]
            general_headers = [cell.value for cell in general_ws[1]]
            single_price = single_ws.cell(
                row=2, column=single_headers.index("판매가") + 1
            ).value
            general_price = general_ws.cell(
                row=2, column=general_headers.index("판매가") + 1
            ).value

        self.assertEqual(setting_ws["R2"].value, "https://order/1")
        self.assertNotIn("주문링크", single_headers)
        self.assertNotIn("주문링크", general_headers)
        self.assertEqual(single_price, 9500)
        self.assertEqual(general_price, 8900)

    def test_export_from_db_fails_before_writing_when_row_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db = tmp / "test.db"
            reference = tmp / "reference.xlsx"
            out = tmp / "out"
            make_reference(reference)
            conn = make_db(db)
            import_crawl(
                conn,
                CrawlData((CrawlRow(1, "상품1", 7080, "https://img/1.jpg", "https://order/1"),), 0),
                category_code="C1", margin=0.15, crawl_path="crawl.xlsx",
            )
            conn.execute("UPDATE products SET order_url=''")
            conn.commit()
            conn.close()

            with self.assertRaisesRegex(ValueError, "order_url"):
                export_from_db(
                    db, reference, out, selected_option="기타재화[35]",
                    run_date=date(2026, 10, 27),
                )
            self.assertFalse(setting_copy_path(out, date(2026, 10, 27)).exists())
            self.assertFalse(output_paths(out, date(2026, 10, 27), False)[0].exists())
