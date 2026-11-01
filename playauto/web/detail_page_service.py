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


def parse_detail_page_form(form) -> dict:
    raw_images = _text(form, "detail_page_extra_images")
    extra_images = [
        part.strip()
        for part in re.split(r"[\n,]+", raw_images)
        if part.strip()
    ][:5]
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
    extra_images = values.get("detail_page_extra_images") or []
    if isinstance(extra_images, str):
        extra_images = [extra_images]
    extra_images = [
        str(url).strip() for url in extra_images if str(url).strip()
    ][:5]
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

    try:
        extra_images = json.loads(product["detail_page_extra_images"] or "[]")
    except (TypeError, ValueError):
        extra_images = []
    if not isinstance(extra_images, list):
        extra_images = []
    extra_images = [
        str(url).strip() for url in extra_images if str(url).strip()
    ][:5]

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
