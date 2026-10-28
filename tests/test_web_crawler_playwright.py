import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from playauto.db import connect, ensure_schema
from playauto.web.crawler import CrawlBlockedError, extract_cards, is_blocked_page
from playauto.web.queries import claim_next_job, create_crawl_job, get_job
from playauto.web.worker import process_job
from tests.web_helpers import make_web_app


class FakePage:
    def __init__(self, cards):
        self.cards = cards

    def evaluate(self, _script):
        return self.cards


class CrawlerIntegrationTests(unittest.TestCase):
    def test_blocked_page_detection(self):
        self.assertTrue(
            is_blocked_page("Just a moment...", "", 0)
        )
        self.assertTrue(
            is_blocked_page("Gmarket", "Verify you are human", 0)
        )
        self.assertFalse(
            is_blocked_page("스타배송 - 카프리썬 검색결과", "", 12)
        )

    def test_extract_cards_returns_raw_contract(self):
        cards = extract_cards(
            FakePage(
                [
                    {
                        "name": "상품",
                        "brand": "브랜드",
                        "price": "1,000원",
                        "image": "//img/1.jpg",
                        "href": "https://item/1",
                    }
                ]
            )
        )
        self.assertEqual(cards[0]["price"], "1,000원")
        self.assertEqual(cards[0]["href"], "https://item/1")

    def test_search_job_imports_cards(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app, db_path = make_web_app(tmp.name)
        conn = connect(db_path)
        ensure_schema(conn)
        self.addCleanup(conn.close)

        job_id = create_crawl_job(
            conn,
            source="search",
            search_url="https://www.gmarket.co.kr/n/stardelivery/search?keyword=x",
            category_code="기타재화[35]",
            margin=0.15,
        )
        job = claim_next_job(conn)
        process_job(
            conn,
            job,
            crawler=lambda _url: [
                {
                    "name": "공식\n상품\n농심\n카프리썬",
                    "brand": "농심",
                    "price": "25,530원",
                    "image": "//img/1.jpg",
                    "href": "https://item/1",
                }
            ],
        )
        result = get_job(conn, job_id)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1
        )

    def test_search_job_with_no_cards_fails(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app, db_path = make_web_app(tmp.name)
        conn = connect(db_path)
        ensure_schema(conn)
        self.addCleanup(conn.close)

        job_id = create_crawl_job(
            conn,
            source="search",
            search_url="https://www.gmarket.co.kr/n/stardelivery/search?keyword=x",
            category_code="기타재화[35]",
            margin=0.15,
        )
        job = claim_next_job(conn)
        process_job(conn, job, crawler=lambda _url: [])
        result = get_job(conn, job_id)
        self.assertEqual(result["status"], "failed")
        self.assertIn("유효한 상품 카드", result["error"])

    def test_search_job_marks_blocked_as_failed(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app, db_path = make_web_app(tmp.name)
        conn = connect(db_path)
        ensure_schema(conn)
        self.addCleanup(conn.close)

        job_id = create_crawl_job(
            conn,
            source="search",
            search_url="https://www.gmarket.co.kr/n/stardelivery/search?keyword=x",
            category_code="기타재화[35]",
            margin=0.15,
        )
        job = claim_next_job(conn)

        def blocked(_url):
            raise CrawlBlockedError("Gmarket이 자동 접속을 차단했습니다.")

        process_job(conn, job, crawler=blocked)
        result = get_job(conn, job_id)
        self.assertEqual(result["status"], "failed")
        self.assertIn("차단", result["error"])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM products").fetchone()[0], 0
        )
