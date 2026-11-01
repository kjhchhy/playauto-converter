import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from playauto.detail_page import build_detail_page_html, pick_palette
from playauto.web.detail_page_image import render_html_to_jpeg

DETAIL_PAGE_DIR = Path("data/detail-pages")


def _text(form, key: str) -> str:
    value = form.get(key, "")
    return str(value or "").strip()


def _normalize_extra_images(value) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[\n,]+", value)
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = []
    return [str(part).strip() for part in parts if str(part).strip()][:5]


def _decode_extra_images(raw) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        value = []
    return _normalize_extra_images(value)


def parse_detail_page_form(form) -> dict:
    extra_images = _normalize_extra_images(
        _text(form, "detail_page_extra_images")
    )
    return {
        "detail_page_title": _text(form, "detail_page_title"),
        "detail_page_marketing": _text(form, "detail_page_marketing"),
        "detail_page_caution": _text(form, "detail_page_caution"),
        "detail_page_extra_images": extra_images,
        "notice_image_url": _text(form, "notice_image_url"),
        "detail_page_url": _text(form, "detail_page_url"),
    }


def save_detail_page(
    conn: sqlite3.Connection, product_id: int, values: dict
) -> None:
    extra_images = _normalize_extra_images(
        values.get("detail_page_extra_images")
    )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        conn.execute(
            "UPDATE products SET "
            "detail_page_title = ?, "
            "detail_page_marketing = ?, "
            "detail_page_caution = ?, "
            "detail_page_extra_images = ?, "
            "notice_image_url = ?, "
            "detail_page_url = ?, "
            "detail_page_updated_at = ?, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (
                values.get("detail_page_title") or None,
                values.get("detail_page_marketing") or None,
                values.get("detail_page_caution") or None,
                json.dumps(extra_images, ensure_ascii=False),
                values.get("notice_image_url") or None,
                values.get("detail_page_url") or None,
                now,
                product_id,
            ),
        )


def generate_detail_page(
    conn: sqlite3.Connection,
    product_id: int,
    *,
    renderer=render_html_to_jpeg,
    palette_seed: int | None = None,
    output_dir: Path | None = None,
) -> Path:
    product = conn.execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    if product is None:
        raise ValueError("상품을 찾을 수 없습니다.")
    notice_image_url = (product["notice_image_url"] or "").strip()
    if not notice_image_url:
        raise ValueError("고시 이미지가 필요합니다.")

    extra_images = _decode_extra_images(product["detail_page_extra_images"])

    html = build_detail_page_html(
        title=product["detail_page_title"] or product["name"],
        marketing=product["detail_page_marketing"] or "",
        caution=product["detail_page_caution"] or "",
        main_image_url=product["image_url"],
        extra_image_urls=extra_images,
        notice_image_url=notice_image_url,
        palette=pick_palette(palette_seed),
    )
    directory = Path(output_dir) if output_dir is not None else DETAIL_PAGE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return renderer(html, directory / f"{product_id}.jpg")
