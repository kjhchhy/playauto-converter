import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from playauto.db import CrawlData, CrawlRow, parse_price

GMARKET_SEARCH_HOST = "www.gmarket.co.kr"
GMARKET_SEARCH_PATH = "/n/stardelivery/search"

CARD_SELECTOR = ".box__itemcard"
CARD_WAIT_MS = 30000
DEFAULT_PROFILE = Path("data/browser-profile")
BLOCKED_STATUSES = frozenset({403, 429, 503})
BLOCKED_MARKERS = (
    "just a moment",
    "verify you are human",
    "cloudflare",
    "잠시만 기다려주십시오",
    "원활한 서비스 이용을 위한 간단한 확인 안내",
    "사람인지 확인하십시오",
)
BLOCKED_MESSAGE = (
    "Gmarket이 자동 요청을 차단했습니다. "
    "크롤 xlsx를 업로드하거나 잠시 후 다시 시도해주세요."
)

_CAPACITY_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(ml|g|개)$", re.IGNORECASE)
_DROP_NAME_LINES = {"공식", "상품"}


class CrawlBlockedError(RuntimeError):
    """Raised when Gmarket serves an anti-bot interstitial page."""


def is_blocked_page(title: str, body_text: str, card_count: int) -> bool:
    if card_count:
        return False
    haystack = f"{title or ''}\n{body_text or ''}".lower()
    return any(marker in haystack for marker in BLOCKED_MARKERS)


def is_blocked_status(status) -> bool:
    try:
        return int(status) in BLOCKED_STATUSES
    except (TypeError, ValueError):
        return False


EXTRACT_CARDS_JS = """
() => {
  const cards = [];
  document.querySelectorAll('.box__itemcard').forEach((card) => {
    const nameEl = card.querySelector('.item_name');
    let name = null;
    if (nameEl) {
      const clone = nameEl.cloneNode(true);
      clone.querySelectorAll('.box__brand').forEach((el) => el.remove());
      name = (clone.textContent || '').trim();
    }
    const brandEl = card.querySelector('.text__brand');
    const priceEl = card.querySelector('.box__price .text__value');
    const imgEl = card.querySelector('.item_image img');
    const linkEl = card.querySelector('a.link__itemcard');
    cards.push({
      name: name,
      brand: brandEl ? (brandEl.textContent || '').trim() : null,
      price: priceEl ? (priceEl.textContent || '').trim() : null,
      image: imgEl
        ? (imgEl.getAttribute('src') || imgEl.getAttribute('data-src') || null)
        : null,
      href: linkEl ? linkEl.getAttribute('href') : null,
    });
  });
  return cards;
}
"""

_PAGE_LINKS_JS = """
() => {
  const read = (a) => {
    const href = a.getAttribute('href');
    if (!href || href.toLowerCase().startsWith('javascript:')) return null;
    return {
      href: href,
      text: (a.textContent || '').trim(),
      active: a.classList.contains('active') || !!a.closest('.active'),
    };
  };
  const pages = Array.from(document.querySelectorAll('.link__page_number'))
    .map(read)
    .filter(Boolean);
  const next = Array.from(
    document.querySelectorAll('.link__next, a[rel="next"], a')
  )
    .filter((a) => {
      const text = (a.textContent || '').trim().toLowerCase();
      return (
        a.matches('.link__next, [rel="next"]') ||
        ['다음', 'next', '>', '›', '»'].includes(text)
      );
    })
    .map(read)
    .filter(Boolean);
  return { pages: pages, next: next };
}
"""


def extract_cards(page) -> list[dict]:
    return page.evaluate(EXTRACT_CARDS_JS)


def _profile_path(browser_profile) -> Path:
    if browser_profile:
        path = Path(browser_profile)
    else:
        path = Path(os.environ.get("BROWSER_PROFILE") or DEFAULT_PROFILE)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _page_number_from_url(url: str) -> int | None:
    try:
        values = parse_qs(urlparse(url).query).get("page")
    except ValueError:
        return None
    if not values:
        return None
    try:
        number = int(str(values[0]).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _page_number_from_text(text: str) -> int | None:
    digits = re.sub(r"\D", "", text or "")
    if not digits:
        return None
    try:
        number = int(digits)
    except ValueError:
        return None
    return number if number > 0 else None


def _current_page_number(page, links: dict) -> int:
    current = _page_number_from_url(getattr(page, "url", "") or "")
    if current is not None:
        return current
    for link in links.get("pages") or ():
        if link.get("active"):
            current = _page_number_from_text(link.get("text"))
            if current is not None:
                return current
    return 1


def _next_page_url(page, visited: set[str]) -> str | None:
    try:
        links = page.evaluate(_PAGE_LINKS_JS)
    except Exception:  # noqa: BLE001 - pagination is best effort
        return None
    if not isinstance(links, dict):
        return None

    current_url = getattr(page, "url", "") or ""
    current = _current_page_number(page, links)

    pages: list[tuple[int | None, str]] = []
    for link in links.get("pages") or ():
        absolute = urljoin(current_url, link.get("href") or "")
        if not absolute or absolute in visited:
            continue
        number = _page_number_from_url(absolute)
        text_number = _page_number_from_text(link.get("text"))
        if number is None or number <= current:
            if text_number is not None:
                number = text_number
        pages.append((number, absolute))

    for number, absolute in pages:
        if number == current + 1:
            return absolute

    for link in links.get("next") or ():
        absolute = urljoin(current_url, link.get("href") or "")
        if absolute and absolute not in visited:
            return absolute

    forward = [
        (number, absolute)
        for number, absolute in pages
        if number is not None and number > current
    ]
    if forward:
        forward.sort(key=lambda item: item[0])
        return forward[0][1]
    return None


def fetch_search_cards(
    search_url: str,
    *,
    max_pages: int = 50,
    max_rows: int = 5000,
    browser_profile=None,
) -> list[dict]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    profile = _profile_path(browser_profile)
    playwright = sync_playwright().start()
    context = None
    try:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=True,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        page = context.pages[0] if context.pages else context.new_page()
        response = page.goto(search_url, wait_until="domcontentloaded")
        if is_blocked_status(getattr(response, "status", None)):
            raise CrawlBlockedError(BLOCKED_MESSAGE)

        cards: list[dict] = []
        try:
            page.wait_for_selector(CARD_SELECTOR, timeout=CARD_WAIT_MS)
        except PlaywrightTimeoutError:
            raise CrawlBlockedError(BLOCKED_MESSAGE) from None

        visited: set[str] = set()
        pagination_visited: set[str] = {getattr(page, "url", "") or ""}
        pages_loaded = 0
        while pages_loaded < max_pages:
            pages_loaded += 1
            page_cards = extract_cards(page) or []
            if not page_cards:
                raise CrawlBlockedError(BLOCKED_MESSAGE)

            new_cards = []
            for card in page_cards:
                href = str(card.get("href") or "")
                if href and href in visited:
                    continue
                if href:
                    visited.add(href)
                new_cards.append(card)

            if not new_cards:
                break
            cards.extend(new_cards)
            if len(cards) >= max_rows or pages_loaded >= max_pages:
                break

            next_url = _next_page_url(page, pagination_visited)
            if not next_url:
                break
            pagination_visited.add(next_url)
            response = page.goto(next_url, wait_until="domcontentloaded")
            if is_blocked_status(getattr(response, "status", None)):
                raise CrawlBlockedError(BLOCKED_MESSAGE)
            try:
                page.wait_for_selector(CARD_SELECTOR, timeout=CARD_WAIT_MS)
            except PlaywrightTimeoutError:
                raise CrawlBlockedError(BLOCKED_MESSAGE) from None

        return cards[:max_rows]
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:  # noqa: BLE001 - cleanup must not mask errors
                pass
        try:
            playwright.stop()
        except Exception:  # noqa: BLE001 - cleanup must not mask errors
            pass


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
