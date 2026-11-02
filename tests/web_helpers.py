from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash

from playauto.db import connect, ensure_schema
from playauto.web.app import create_app


def new_conn(tmpdir):
    conn = connect(Path(tmpdir) / "test.db")
    ensure_schema(conn)
    return conn


def seed_product(
    conn,
    *,
    seq=1,
    name="테스트 상품",
    price=1000,
    brand="테스트브랜드",
    seller_code="MJ-0001",
    category_code="기타재화[35]",
    margin=0.15,
    order_url=None,
):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    order_url = order_url or f"https://item.gmarket.co.kr/Item?goodscode={seq}"
    product = conn.execute(
        "INSERT INTO products ("
        "source_seq, name, image_url, order_url, category_code, brand, "
        "created_at, updated_at, last_seen_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            seq,
            name,
            f"https://gdimg.gmarket.co.kr/{seq}/still/400",
            order_url,
            category_code,
            brand,
            now,
            now,
            now,
        ),
    )
    product_id = product.lastrowid
    listing = conn.execute(
        "INSERT INTO listings ("
        "product_id, seller_code, bundle_qty, sale_name, market_price, "
        "margin_rate, active, created_at, updated_at"
        ") VALUES (?, ?, 1, ?, ?, ?, 1, ?, ?)",
        (product_id, seller_code, name, price, margin, now, now),
    )
    listing_id = listing.lastrowid
    conn.execute(
        "INSERT INTO price_history ("
        "product_id, listing_id, price, observed_at"
        ") VALUES (?, ?, ?, ?)",
        (product_id, listing_id, price, now),
    )
    conn.commit()
    return product_id, listing_id


def make_web_app(tmpdir, password="secret"):
    db_path = Path(tmpdir) / "test.db"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "ADMIN_PASSWORD_HASH": generate_password_hash(password),
            "DATABASE": str(db_path),
            "REFERENCE_PATH": str(Path(tmpdir) / "current.xlsx"),
            "EXPORT_ROOT": str(Path(tmpdir) / "exports"),
            "UPLOAD_ROOT": str(Path(tmpdir) / "uploads"),
            "BROWSER_PROFILE": str(Path(tmpdir) / "browser"),
            "EXPORT_TTL_HOURS": 24,
        }
    )
    return app, db_path


def login(client, password="secret"):
    client.get("/login")
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    return client.post(
        "/login", data={"password": password, "csrf_token": token}
    )


def post_with_csrf(client, url, data):
    with client.session_transaction() as session:
        token = session["_csrf_token"]
    return client.post(url, data={**data, "csrf_token": token})
