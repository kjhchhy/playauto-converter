import sqlite3

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
