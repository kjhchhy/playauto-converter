import unittest

from playauto.web.crawler import (
    normalize_cards,
    parse_capacity,
    unit_price,
    validate_search_url,
)


class CrawlerParsingTests(unittest.TestCase):
    def test_validate_search_url_accepts_gmarket_stardelivery(self):
        validate_search_url(
            "https://www.gmarket.co.kr/n/stardelivery/search?keyword=%EC%B9%B4%ED%94%84%EB%A6%AC%EC%8D%AC"
        )

    def test_validate_search_url_rejects_other_urls(self):
        for url in (
            "http://www.gmarket.co.kr/n/stardelivery/search?keyword=x",
            "https://item.gmarket.co.kr/Item?goodscode=1",
            "https://www.gmarket.co.kr/n/other?keyword=x",
            "https://www.gmarket.co.kr/n/stardelivery/search",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_search_url(url)

    def test_normalize_cards_cleans_name_and_price(self):
        data = normalize_cards(
            [
                {
                    "name": "공식\n상품\n농심\n농심 카프리썬 40개 골라담기",
                    "brand": "농심",
                    "price": "25,530원",
                    "image": "//gdimg.gmarket.co.kr/1/still/400",
                    "href": "https://item.gmarket.co.kr/Item?goodscode=1",
                }
            ]
        )
        self.assertEqual(len(data.rows), 1)
        row = data.rows[0]
        self.assertEqual(row.source_seq, 1)
        self.assertEqual(row.name, "카프리썬 40개 골라담기")
        self.assertEqual(row.brand, "농심")
        self.assertEqual(row.market_price, 25530)
        self.assertEqual(
            row.image_url, "https://gdimg.gmarket.co.kr/1/still/400"
        )
        self.assertEqual(
            row.order_url, "https://item.gmarket.co.kr/Item?goodscode=1"
        )

    def test_normalize_cards_skips_invalid_and_keeps_last_duplicate(self):
        cards = [
            {
                "name": "첫 상품",
                "brand": "A",
                "price": "1,000",
                "image": "https://img/1.jpg",
                "href": "https://item/1",
            },
            {
                "name": "가격 없음",
                "brand": "B",
                "price": "",
                "image": "https://img/2.jpg",
                "href": "https://item/2",
            },
            {
                "name": "마지막 상품",
                "brand": "A",
                "price": "3,000",
                "image": "https://img/1b.jpg",
                "href": "https://item/1",
            },
        ]
        data = normalize_cards(cards)
        self.assertEqual(len(data.rows), 1)
        self.assertEqual(data.rows[0].name, "마지막 상품")
        self.assertEqual(data.rows[0].market_price, 3000)
        self.assertEqual(data.skipped, 1)

    def test_parse_capacity_and_unit_price(self):
        self.assertEqual(parse_capacity("200ml"), (200.0, "ml"))
        self.assertEqual(parse_capacity("100g"), (100.0, "g"))
        self.assertEqual(parse_capacity("40개"), (40.0, "개"))
        self.assertIsNone(parse_capacity("대용량"))
        self.assertEqual(unit_price(25530, "200ml"), (12765.0, "100ml"))
        self.assertEqual(unit_price(25530, "100g"), (25530.0, "100g"))
        self.assertEqual(unit_price(25530, "40개"), (638.25, "개"))
        self.assertIsNone(unit_price(25530, "대용량"))
