import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook

from playauto.db import connect, ensure_schema
from playauto.web.queries import (
    claim_next_job,
    create_crawl_job,
    get_job,
    mark_stale_jobs,
)
from playauto.web.worker import process_job
from tests.web_helpers import make_web_app, seed_product


def make_crawl_xlsx(path, headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app, self.db_path = make_web_app(self.tmp.name)
        self.conn = connect(self.db_path)
        ensure_schema(self.conn)
        self.addCleanup(self.conn.close)

    def test_create_and_claim_job(self):
        job_id = create_crawl_job(
            self.conn,
            source="xlsx",
            xlsx_path="x.xlsx",
            category_code="기타재화[35]",
            margin=0.15,
        )
        job = claim_next_job(self.conn)
        self.assertEqual(job["id"], job_id)
        self.assertEqual(job["status"], "running")
        self.assertIsNone(claim_next_job(self.conn))

    def test_xlsx_upload_rejects_non_xlsx(self):
        from io import BytesIO

        from tests.web_helpers import login

        client = self.app.test_client()
        login(client)
        with client.session_transaction() as session:
            token = session["_csrf_token"]
        response = client.post(
            "/imports/xlsx",
            data={"csrf_token": token, "file": (BytesIO(b"x"), "x.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)

    def test_claim_skips_running_and_finished(self):
        create_crawl_job(
            self.conn,
            source="xlsx",
            xlsx_path="a.xlsx",
            category_code="기타재화[35]",
            margin=0.15,
        )
        second = create_crawl_job(
            self.conn,
            source="xlsx",
            xlsx_path="b.xlsx",
            category_code="기타재화[35]",
            margin=0.15,
        )
        first_job = claim_next_job(self.conn)
        self.assertIsNotNone(first_job)
        self.assertEqual(claim_next_job(self.conn)["id"], second)

    def test_stale_running_job_marked_failed(self):
        job_id = create_crawl_job(
            self.conn,
            source="xlsx",
            xlsx_path="x.xlsx",
            category_code="기타재화[35]",
            margin=0.15,
        )
        claim_next_job(self.conn)
        self.conn.execute(
            "UPDATE crawl_jobs SET started_at='2000-01-01T00:00:00+00:00' "
            "WHERE id=?",
            (job_id,),
        )
        self.conn.commit()
        self.assertEqual(mark_stale_jobs(self.conn), 1)
        result = get_job(self.conn, job_id)
        self.assertEqual(result["status"], "failed")
        self.assertIn("중단", result["error"])

    def test_xlsx_job_imports_rows_and_cleans_file(self):
        crawl = Path(self.tmp.name) / "crawl.xlsx"
        make_crawl_xlsx(
            crawl,
            ["순번", "대표이미지", "상품명", "판매가격", "URL", "브랜드"],
            [
                [
                    1,
                    "https://img/1.jpg",
                    "카프리썬",
                    "25,530원",
                    "https://item.gmarket.co.kr/Item?goodscode=1",
                    "농심",
                ]
            ],
        )
        job_id = create_crawl_job(
            self.conn,
            source="xlsx",
            xlsx_path=str(crawl),
            category_code="기타재화[35]",
            margin=0.15,
        )
        job = claim_next_job(self.conn)
        process_job(self.conn, job)
        result = get_job(self.conn, job_id)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["inserted_count"], 1)
        self.assertFalse(crawl.exists())
        product = self.conn.execute(
            "SELECT name, brand FROM products"
        ).fetchone()
        self.assertEqual(product["name"], "카프리썬")
        self.assertEqual(product["brand"], "농심")

    def test_xlsx_missing_header_marks_failed_and_cleans_file(self):
        crawl = Path(self.tmp.name) / "bad.xlsx"
        make_crawl_xlsx(crawl, ["상품명"], [["상품"]])
        job_id = create_crawl_job(
            self.conn,
            source="xlsx",
            xlsx_path=str(crawl),
            category_code="기타재화[35]",
            margin=0.15,
        )
        job = claim_next_job(self.conn)
        process_job(self.conn, job)
        result = get_job(self.conn, job_id)
        self.assertEqual(result["status"], "failed")
        self.assertIn("누락 헤더", result["error"])
        self.assertFalse(crawl.exists())

    def test_reimport_preserves_edits_and_adds_history(self):
        first = Path(self.tmp.name) / "first.xlsx"
        second = Path(self.tmp.name) / "second.xlsx"
        headers = ["순번", "대표이미지", "상품명", "판매가격", "URL"]
        make_crawl_xlsx(
            first,
            headers,
            [[1, "https://img/1.jpg", "카프리썬", "1,000", "https://item/1"]],
        )
        make_crawl_xlsx(
            second,
            headers,
            [[1, "https://img/1.jpg", "카프리썬", "2,000", "https://item/1"]],
        )
        create_crawl_job(
            self.conn,
            source="xlsx",
            xlsx_path=str(first),
            category_code="기타재화[35]",
            margin=0.15,
        )
        process_job(self.conn, claim_next_job(self.conn))

        self.conn.execute(
            "UPDATE listings SET margin_rate=0.25 WHERE seller_code='MJ-0001'"
        )
        self.conn.commit()

        create_crawl_job(
            self.conn,
            source="xlsx",
            xlsx_path=str(second),
            category_code="기타재화[35]",
            margin=0.15,
        )
        process_job(self.conn, claim_next_job(self.conn))

        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1
        )
        listing = self.conn.execute(
            "SELECT market_price, margin_rate FROM listings"
        ).fetchone()
        self.assertEqual(listing["market_price"], 2000)
        self.assertAlmostEqual(listing["margin_rate"], 0.25)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM price_history"
            ).fetchone()[0],
            2,
        )
