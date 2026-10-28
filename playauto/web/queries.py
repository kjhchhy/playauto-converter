import os
import sqlite3
from datetime import datetime, timedelta, timezone

TERMINAL_JOB_STATUSES = ("succeeded", "failed", "interrupted", "canceled")

CRAWL_JOB_FIELDS = (
    "status",
    "started_at",
    "finished_at",
    "page_count",
    "row_count",
    "inserted_count",
    "updated_count",
    "skipped_count",
    "import_batch_id",
    "error",
    "worker_pid",
    "search_url",
    "xlsx_path",
    "category_code",
    "margin",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


PRODUCT_FIELDS = (
    "name",
    "category_code",
    "detail",
    "keywords",
    "manufacturer",
    "brand",
    "model",
)

LISTING_FIELDS = (
    "sale_name",
    "margin_rate",
    "unit_price_visible",
    "display_capacity",
    "display_unit",
    "pack_config",
    "capacity_per_unit",
)

PRODUCT_SELECT = """
SELECT p.id, p.source_seq, p.name, p.image_url, p.order_url,
       p.category_code, p.detail, p.keywords, p.manufacturer, p.brand,
       p.model, p.created_at, p.updated_at, p.last_seen_at,
       l.id AS listing_id, l.seller_code, l.bundle_qty, l.sale_name,
       l.market_price, l.margin_rate, l.unit_price_visible,
       l.display_capacity, l.display_unit, l.pack_config,
       l.capacity_per_unit
FROM products p
JOIN listings l ON l.product_id = p.id
WHERE l.bundle_qty = 1 AND l.active = 1
"""

SEARCH_FIELDS = ("p.name", "p.brand", "l.seller_code", "p.order_url")


def _filters(
    *,
    q=None,
    category=None,
    brand=None,
    min_price=None,
    max_price=None,
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []

    if q:
        pattern = f"%{q}%"
        clauses.append(
            "(" + " OR ".join(f"{field} LIKE ?" for field in SEARCH_FIELDS) + ")"
        )
        params.extend([pattern] * len(SEARCH_FIELDS))
    if category:
        clauses.append("p.category_code = ?")
        params.append(category)
    if brand:
        clauses.append("p.brand = ?")
        params.append(brand)
    if min_price is not None:
        clauses.append("l.market_price >= ?")
        params.append(min_price)
    if max_price is not None:
        clauses.append("l.market_price <= ?")
        params.append(max_price)

    if not clauses:
        return "", params
    return " AND " + " AND ".join(clauses), params


def list_products(
    conn: sqlite3.Connection,
    *,
    q=None,
    category=None,
    brand=None,
    min_price=None,
    max_price=None,
    page=1,
    per_page=50,
) -> tuple[list[sqlite3.Row], int]:
    where, params = _filters(
        q=q,
        category=category,
        brand=brand,
        min_price=min_price,
        max_price=max_price,
    )

    total = conn.execute(
        "SELECT COUNT(*) FROM products p "
        "JOIN listings l ON l.product_id = p.id "
        "WHERE l.bundle_qty = 1 AND l.active = 1" + where,
        params,
    ).fetchone()[0]

    page = max(1, int(page))
    per_page = max(1, int(per_page))
    offset = (page - 1) * per_page
    rows = conn.execute(
        PRODUCT_SELECT
        + where
        + " ORDER BY p.id DESC LIMIT ? OFFSET ?",
        [*params, per_page, offset],
    ).fetchall()
    return rows, total


def get_product_detail(conn: sqlite3.Connection, product_id: int) -> dict | None:
    product = conn.execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    if product is None:
        return None

    listing = conn.execute(
        "SELECT * FROM listings "
        "WHERE product_id = ? AND bundle_qty = 1 AND active = 1 "
        "ORDER BY id LIMIT 1",
        (product_id,),
    ).fetchone()
    history = conn.execute(
        "SELECT * FROM price_history WHERE product_id = ? "
        "ORDER BY observed_at DESC, id DESC",
        (product_id,),
    ).fetchall()
    return {"product": product, "listing": listing, "history": history}


def _update(
    conn: sqlite3.Connection,
    table: str,
    row_id: int,
    data: dict,
    allowed: tuple[str, ...],
) -> bool:
    updates = {
        key: value
        for key, value in data.items()
        if key in allowed
    }
    if not updates:
        return False

    assignments = ", ".join(f"{key} = ?" for key in updates)
    params = [*updates.values(), row_id]
    with conn:
        cursor = conn.execute(
            f"UPDATE {table} SET {assignments}, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )
        return cursor.rowcount > 0


def update_product(
    conn: sqlite3.Connection, product_id: int, data: dict
) -> bool:
    return _update(conn, "products", product_id, data, PRODUCT_FIELDS)


def update_listing(
    conn: sqlite3.Connection, listing_id: int, data: dict
) -> bool:
    return _update(conn, "listings", listing_id, data, LISTING_FIELDS)


def create_crawl_job(
    conn: sqlite3.Connection,
    *,
    source: str,
    category_code: str,
    margin: float,
    search_url: str | None = None,
    xlsx_path: str | None = None,
) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO crawl_jobs ("
            "status, source, search_url, xlsx_path, category_code, margin"
            ") VALUES ('queued', ?, ?, ?, ?, ?)",
            (source, search_url, xlsx_path, category_code, margin),
        )
        return cursor.lastrowid


def list_jobs(
    conn: sqlite3.Connection, limit: int = 20
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM crawl_jobs ORDER BY id DESC LIMIT ?", (int(limit),)
    ).fetchall()


def get_job(
    conn: sqlite3.Connection, job_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)
    ).fetchone()


def claim_next_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    now = _utc_now()
    pid = os.getpid()
    with conn:
        row = conn.execute(
            "UPDATE crawl_jobs SET status = 'running', started_at = ?, "
            "worker_pid = ? "
            "WHERE id = ("
            "  SELECT id FROM crawl_jobs "
            "  WHERE status = 'queued' ORDER BY id LIMIT 1"
            ") RETURNING id",
            (now, pid),
        ).fetchone()
    if row is None:
        return None
    return get_job(conn, row["id"])


def mark_stale_jobs(
    conn: sqlite3.Connection, *, older_than_minutes: int = 30
) -> int:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    ).isoformat(timespec="seconds")
    with conn:
        cursor = conn.execute(
            "UPDATE crawl_jobs SET status = 'failed', "
            "error = 'worker 중단됨', finished_at = ? "
            "WHERE status = 'running' "
            "AND (started_at IS NULL OR started_at < ?)",
            (_utc_now(), cutoff),
        )
        return cursor.rowcount


def update_job(
    conn: sqlite3.Connection, job_id: int, **fields
) -> None:
    updates = {
        key: value for key, value in fields.items() if key in CRAWL_JOB_FIELDS
    }
    if not updates:
        return
    if (
        updates.get("status") in TERMINAL_JOB_STATUSES
        and "finished_at" not in updates
    ):
        updates["finished_at"] = _utc_now()

    assignments = ", ".join(f"{key} = ?" for key in updates)
    with conn:
        conn.execute(
            f"UPDATE crawl_jobs SET {assignments} WHERE id = ?",
            [*updates.values(), job_id],
        )
