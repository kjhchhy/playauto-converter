import re
from urllib.parse import parse_qs, urlparse

from playauto.db import CrawlData, CrawlRow, parse_price

GMARKET_SEARCH_HOST = "www.gmarket.co.kr"
GMARKET_SEARCH_PATH = "/n/stardelivery/search"

_CAPACITY_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(ml|g|개)$", re.IGNORECASE)
_DROP_NAME_LINES = {"공식", "상품"}


def validate_search_url(url: str) -> None:
    if not isinstance(url, str):
        raise ValueError("검색 URL이 올바르지 않습니다.")
    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise ValueError("검색 URL은 HTTPS여야 합니다.")
    if parsed.hostname != GMARKET_SEARCH_HOST:
        raise ValueError("지원하지 않는 검색 호스트입니다.")
    if parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("검색 URL에 허용되지 않는 접속 정보가 있습니다.")
    if parsed.path != GMARKET_SEARCH_PATH:
        raise ValueError("지원하지 않는 검색 경로입니다.")
    keywords = parse_qs(parsed.query, keep_blank_values=True).get("keyword")
    if not keywords or not keywords[0].strip():
        raise ValueError("검색어가 필요합니다.")


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_name(name: str, brand: str | None) -> str:
    brand_text = _text(brand)
    lines = [line.strip() for line in name.splitlines()]
    kept = []
    for line in lines:
        if not line:
            continue
        if line in _DROP_NAME_LINES:
            continue
        if brand_text and line == brand_text:
            continue
        kept.append(line)
    if not kept:
        return ""
    first = kept[0]
    if brand_text and first.startswith(brand_text):
        first = first[len(brand_text):]
    text = " ".join([first, *kept[1:]])
    return re.sub(r"\s+", " ", text).strip()


def normalize_cards(raw_cards: list[dict]) -> CrawlData:
    ordered: list[dict] = []
    index_by_url: dict[str, int] = {}
    skipped = 0
    for card in raw_cards or ():
        href = _text(card.get("href"))
        name = _text(card.get("name"))
        price = _text(card.get("price"))
        image = _text(card.get("image"))
        if not href or not name or not price or not image:
            skipped += 1
            continue
        try:
            market_price = parse_price(price)
        except ValueError:
            skipped += 1
            continue
        brand = _text(card.get("brand")) or None
        cleaned_name = _clean_name(name, brand)
        if not cleaned_name:
            skipped += 1
            continue
        image_url = image if not image.startswith("//") else f"https:{image}"
        row_data = {
            "name": cleaned_name,
            "brand": brand,
            "market_price": market_price,
            "image_url": image_url,
            "order_url": href,
        }
        position = index_by_url.get(href)
        if position is None:
            index_by_url[href] = len(ordered)
            ordered.append(row_data)
        else:
            ordered[position] = row_data
    rows = tuple(
        CrawlRow(source_seq=seq, **row_data)
        for seq, row_data in enumerate(ordered, start=1)
    )
    return CrawlData(rows=rows, skipped=skipped)


def parse_capacity(text: str | None) -> tuple[float, str] | None:
    if text is None:
        return None
    match = _CAPACITY_RE.match(str(text).strip())
    if match is None:
        return None
    unit = match.group(2)
    unit = unit.lower() if unit.lower() in {"ml", "g"} else "개"
    return float(match.group(1)), unit


def unit_price(
    market_price: int,
    capacity_per_unit: str | None,
    bundle_qty: int = 1,
) -> tuple[float, str] | None:
    parsed = parse_capacity(capacity_per_unit)
    if parsed is None:
        return None
    capacity, unit = parsed
    try:
        qty = int(bundle_qty)
    except (TypeError, ValueError):
        return None
    total = capacity * qty
    if total <= 0:
        return None
    if unit in {"ml", "g"}:
        value = float(market_price) * 100 / total
        return value, f"100{unit}"
    return float(market_price) / total, "개"
