import re
from dataclasses import dataclass

UNIT_PRICE_FLAG_SOURCE = "단위 가격 표시 여부"
UNIT_PRICE_FLAG_OUTPUT = "단위 가격 표시 여부"
UNIT_PRICE_VALUE_HEADERS = ["표시 용량", "표시 단위", "구성 방식", "개당 용량"]
UNIT_PRICE_SOURCE_HEADERS = [UNIT_PRICE_FLAG_SOURCE, *UNIT_PRICE_VALUE_HEADERS]
UNIT_PRICE_OUTPUT_HEADERS = [UNIT_PRICE_FLAG_OUTPUT, *UNIT_PRICE_VALUE_HEADERS]
COUPANG_OPTION_HEADERS = ["옵션 바코드", "옵션 모델번호"]

SETTING_HEADERS = [
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
]

GENERAL_BASE_HEADERS = [
    "쇼핑몰(계정)",
    "템플릿코드",
    "머리말/꼬리말 템플릿코드",
    "카테고리코드",
    "템플릿코드정보",
    "판매자관리코드",
    "온라인 상품명",
    "기본이미지",
    "상세설명",
    "키워드",
    "제조사",
    "브랜드",
    "모델명",
    "과세여부",
    "판매가",
    "판매수량",
    "옵션조합",
    "옵션",
    "원산지",
    "배송방법",
    "배송비",
    "인증유형",
    "미성년자 구매",
]

SINGLE_BASE_HEADERS = [
    "쇼핑몰(계정)",
    "템플릿코드",
    "머리말/꼬리말 템플릿코드",
    "카테고리코드",
    "템플릿코드정보",
    "판매자관리코드",
    "온라인 상품명",
    "기본이미지",
    "상세설명",
    "키워드",
    "제조사",
    "브랜드",
    "모델명",
    "과세여부",
    "판매가",
    "판매수량",
    "옵션조합",
    "원산지",
    "배송방법",
    "배송비",
    "인증유형",
    "미성년자 구매",
    "공급가",
    "원가",
    "시중가",
    "프로모션용 상품명",
    "복수원산지 여부",
    "상품명 머리말/꼬리말 템플릿코드",
    "UPC/EAN코드",
    "ISBN코드",
    "바코드",
    "인증정보",
    "사은품",
    "제조일자",
    "유효일자",
]

PRODUCT_CODE_META = {
    "기타재화[35]": (8, "과세"),
    "기타재화_유아동[35]": (8, "면세"),
    "가공식품[21]": (22, "과세"),
    "가공식품_유아동[21]": (22, "면세"),
    "건강기능식품[22]": (24, "과세"),
    "화장품[18]": (14, "과세"),
    "스포츠용품[25]": (15, "과세"),
    "소형가전[12]": (16, "과세"),
    "농축산물[20]": (17, "면세"),
}


@dataclass(frozen=True)
class ProductMeta:
    product_code: str
    notice_count: int
    tax_status: str


def meta_for_option(selected_option):
    option = str(selected_option).strip()
    meta = PRODUCT_CODE_META.get(option)
    match = re.search(r"\[(\d+)\]", option)
    if meta is None or match is None:
        raise ValueError(f"상품분류코드 형식이 올바르지 않습니다: {selected_option}")
    return ProductMeta(match.group(1), meta[0], meta[1])


def build_setting_headers():
    return list(SETTING_HEADERS)


def build_notice_headers(notice_count):
    return [f"상품정보제공고시 {i}" for i in range(1, int(notice_count) + 1)]


def build_output_headers(mode, notice_count, coupang_single=False):
    if mode in ("general", "일반"):
        base = [*GENERAL_BASE_HEADERS, *UNIT_PRICE_OUTPUT_HEADERS, "상품분류코드"]
    elif mode in ("single", "단일"):
        base = [*SINGLE_BASE_HEADERS, *UNIT_PRICE_OUTPUT_HEADERS, "상품분류코드"]
        if coupang_single:
            option_index = base.index("옵션조합") + 1
            base[option_index:option_index] = ["옵션", *COUPANG_OPTION_HEADERS]
    else:
        raise ValueError(f"unknown mode: {mode}")
    return base + build_notice_headers(notice_count)
