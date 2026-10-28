import math
import time
from urllib.parse import unquote, urlsplit

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from playauto.db import delete_product

from .auth import check_password, csrf_token, login_required
from .queries import (
    get_product_detail,
    list_products,
    update_listing,
    update_product,
)

bp = Blueprint("main", __name__)

LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 60


class LoginRateLimiter:
    def __init__(
        self,
        max_failures: int = LOGIN_MAX_FAILURES,
        window_seconds: int = LOGIN_WINDOW_SECONDS,
        clock=time.monotonic,
    ):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, list[float]] = {}

    def _prune(self, key: str, now: float) -> None:
        cutoff = now - self.window_seconds
        recent = [at for at in self._failures.get(key, ()) if at > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)

    def is_blocked(self, key: str) -> bool:
        now = self._clock()
        self._prune(key, now)
        return len(self._failures.get(key, ())) >= self.max_failures

    def record_failure(self, key: str) -> None:
        now = self._clock()
        self._prune(key, now)
        self._failures.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


def _client_ip() -> str:
    return request.remote_addr or "unknown"


def _db():
    from .app import get_db

    return get_db()


def _limiter() -> LoginRateLimiter:
    return current_app.extensions["login_limiter"]


def _safe_next(target: str | None) -> str:
    fallback = url_for("main.dashboard")
    if not target or not target.startswith("/") or target.startswith("//"):
        return fallback
    if "\\" in target:
        return fallback

    decoded = unquote(target)
    if any(
        ch == "\\" or ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F
        for ch in decoded
    ):
        return fallback
    if not decoded.startswith("/") or decoded.startswith("//"):
        return fallback

    try:
        parts = urlsplit(decoded)
    except ValueError:
        return fallback
    if parts.scheme or parts.netloc:
        return fallback

    return target


@bp.get("/login")
def login():
    if session.get("logged_in"):
        return redirect(url_for("main.dashboard"))
    return render_template("login.html", next=request.args.get("next", ""))


@bp.post("/login")
def login_submit():
    limiter = _limiter()
    ip = _client_ip()
    if limiter.is_blocked(ip):
        return (
            render_template(
                "login.html",
                next=request.form.get("next", ""),
                error="로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.",
            ),
            429,
        )

    password = request.form.get("password", "")
    if not check_password(password, current_app.config["ADMIN_PASSWORD_HASH"]):
        limiter.record_failure(ip)
        return (
            render_template(
                "login.html",
                next=request.form.get("next", ""),
                error="비밀번호가 올바르지 않습니다.",
            ),
            200,
        )

    limiter.reset(ip)
    session.clear()
    session["logged_in"] = True
    csrf_token(session)
    return redirect(_safe_next(request.form.get("next")))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


@bp.get("/")
@login_required
def dashboard():
    return render_template("dashboard.html")


def _optional_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nonnegative_int(value, default):
    parsed = _optional_int(value)
    if parsed is None or parsed < 1:
        return default
    return parsed


@bp.get("/products")
@login_required
def products():
    page = _nonnegative_int(request.args.get("page"), 1)
    per_page = 50
    filters = {
        "q": request.args.get("q") or None,
        "category": request.args.get("category") or None,
        "brand": request.args.get("brand") or None,
        "min_price": _optional_int(request.args.get("min_price")),
        "max_price": _optional_int(request.args.get("max_price")),
    }
    rows, total = list_products(
        _db(),
        page=page,
        per_page=per_page,
        **filters,
    )
    pages = max(1, math.ceil(total / per_page))
    return render_template(
        "products.html",
        products=rows,
        total=total,
        page=page,
        pages=pages,
        per_page=per_page,
        filters=filters,
    )


@bp.get("/products/<int:product_id>")
@login_required
def product_detail(product_id: int):
    detail = get_product_detail(_db(), product_id)
    if detail is None:
        abort(404)
    return render_template("product_detail.html", **detail)


@bp.post("/products/<int:product_id>")
@login_required
def product_update(product_id: int):
    conn = _db()
    detail = get_product_detail(conn, product_id)
    if detail is None:
        abort(404)

    listing = detail["listing"]

    margin = None
    if request.form.get("margin_rate", "").strip():
        try:
            margin = float(request.form["margin_rate"])
        except (TypeError, ValueError):
            margin = None
        if margin is None or not 0 <= margin < 1:
            flash("마진율은 0 이상 1 미만이어야 합니다.", "error")
            return redirect(url_for("main.product_detail", product_id=product_id))

    product_data = {
        key: request.form[key]
        for key in (
            "name",
            "category_code",
            "detail",
            "keywords",
            "manufacturer",
            "brand",
            "model",
        )
        if key in request.form
    }
    listing_data = {
        key: request.form[key]
        for key in (
            "sale_name",
            "unit_price_visible",
            "display_capacity",
            "display_unit",
            "pack_config",
            "capacity_per_unit",
        )
        if key in request.form
    }
    if margin is not None:
        listing_data["margin_rate"] = margin

    update_product(conn, product_id, product_data)
    if listing is not None:
        update_listing(conn, listing["id"], listing_data)

    flash("상품 정보를 저장했습니다.")
    return redirect(url_for("main.product_detail", product_id=product_id))


@bp.post("/products/<int:product_id>/delete")
@login_required
def product_delete(product_id: int):
    conn = _db()
    if get_product_detail(conn, product_id) is None:
        abort(404)
    delete_product(conn, product_id)
    flash("상품을 삭제했습니다.")
    return redirect(url_for("main.products"))


@bp.post("/products/delete")
@login_required
def products_bulk_delete():
    conn = _db()
    deleted = 0
    for raw in request.form.getlist("ids"):
        try:
            product_id = int(raw)
        except (TypeError, ValueError):
            continue
        deleted += delete_product(conn, product_id)
    flash(f"{deleted}개 상품을 삭제했습니다.")
    return redirect(url_for("main.products"))
