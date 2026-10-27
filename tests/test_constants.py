import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from playauto.constants import (
    COUPANG_OPTION_HEADERS,
    UNIT_PRICE_OUTPUT_HEADERS,
    build_notice_headers,
    build_output_headers,
    build_setting_headers,
    meta_for_option,
)


class ConstantsTests(unittest.TestCase):
    def test_setting_headers_match_source_sheet(self):
        self.assertEqual(
            build_setting_headers(),
            [
                "카테고리코드",
                "템플릿코드정보",
                "판매자관리코드",
                "온라인 상품명",
                "시장가격",
                "마진율",
                "기본이미지",
                "상세설명",
                "키워드",
                "제조사",
                "브랜드",
                "모델명",
                "단위 가격 표시 여부",
                "표시 용량",
                "표시 단위",
                "개당 용량",
                "구성 방식",
                "",
            ],
        )

    def test_unit_price_output_order_differs_from_setting_order(self):
        self.assertEqual(
            UNIT_PRICE_OUTPUT_HEADERS,
            ["단위 가격 표시 여부", "표시 용량", "표시 단위", "구성 방식", "개당 용량"],
        )

    def test_general_headers_include_option_and_unit_price_block(self):
        headers = build_output_headers("일반", notice_count=8)
        self.assertIn("옵션", headers)
        self.assertNotIn("공급가", headers)
        self.assertEqual(
            headers[headers.index("미성년자 구매") + 1 : headers.index("상품분류코드")],
            UNIT_PRICE_OUTPUT_HEADERS,
        )
        self.assertEqual(headers[-8:], build_notice_headers(8))
        self.assertEqual(headers.count("상품분류코드"), 1)

    def test_single_headers_include_coupang_options_only_when_requested(self):
        plain = build_output_headers("단일", notice_count=8)
        self.assertNotIn("옵션", plain)
        self.assertIn("공급가", plain)
        self.assertEqual(plain.count("상품분류코드"), 1)

        coupang = build_output_headers("단일", notice_count=8, coupang_single=True)
        start = coupang.index("옵션조합") + 1
        self.assertEqual(
            coupang[start : start + 1 + len(COUPANG_OPTION_HEADERS)],
            ["옵션", *COUPANG_OPTION_HEADERS],
        )

    def test_product_code_metadata(self):
        meta = meta_for_option("화장품[18]")
        self.assertEqual(meta.product_code, "18")
        self.assertEqual(meta.notice_count, 14)
        self.assertEqual(meta.tax_status, "과세")
        self.assertEqual(meta_for_option("기타재화[35]").notice_count, 8)

    def test_unknown_product_code_is_rejected(self):
        with self.assertRaises(ValueError):
            meta_for_option("없는분류")


if __name__ == "__main__":
    unittest.main()
