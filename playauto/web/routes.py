import math
import os
import sqlite3
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from playauto.constants import PRODUCT_CODE_META, meta_for_option
from playauto.db import delete_product
from playauto.pricing import final_sale_price

from .auth import check_password, csrf_token, login_required
from .crawler import unit_price
from .export_service import (
    delete_export,
    export_file,
    export_to_dir,
    list_exports,
    save_reference,
)
from .queries import (
    create_crawl_job,
    ensure_default_settings,
    get_job,
    get_product_detail,
    get_setting,
    list_compare_rows,
    list_jobs,
    list_products,
    mark_stale_jobs,
    set_settings,
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
    conn = _db()
    active_products = conn.execute(
        "SELECT COUNT(DISTINCT p.id) FROM products p "
        "JOIN listings l ON l.product_id = p.id "
        "WHERE l.active = 1 AND l.bundle_qty = 1"
    ).fetchone()[0]
    active_listings = conn.execute(
        "SELECT COUNT(*) FROM listings "
        "WHERE active = 1 AND bundle_qty = 1"
    ).fetchone()[0]
    return render_template(
        "dashboard.html",
        active_products=active_products,
        active_listings=active_listings,
        recent_jobs=list_jobs(conn, 5),
        recent_exports=list_exports(current_app.config["EXPORT_ROOT"])[:5],
    )


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


def _job_margin(value):
    try:
        margin = float(value)
    except (TypeError, ValueError):
        return None
    if not 0 <= margin < 1:
        return None
    return margin


def _imports_context(error=None):
    conn = _db()
    mark_stale_jobs(conn)
    return {"jobs": list_jobs(conn), "error": error}


@bp.get("/imports")
@login_required
def imports():
    return render_template("imports.html", **_imports_context())


@bp.post("/imports")
@login_required
def imports_search_submit():
    search_url = (request.form.get("search_url") or "").strip()
    category_code = (request.form.get("category_code") or "").strip()
    margin = _job_margin(request.form.get("margin"))

    try:
        from playauto.web.crawler import validate_search_url
    except ImportError:
        return (
            render_template(
                "imports.html",
                **_imports_context(
                    "검색 URL 검증 기능을 사용할 수 없습니다. "
                    "엑셀 업로드를 이용해 주세요."
                ),
            ),
            400,
        )

    try:
        if not search_url:
            raise ValueError("검색 URL을 입력해 주세요.")
        validate_search_url(search_url)
    except ValueError as exc:
        return (
            render_template("imports.html", **_imports_context(str(exc))),
            400,
        )

    if not category_code:
        return (
            render_template(
                "imports.html",
                **_imports_context("카테고리 코드를 입력해 주세요."),
            ),
            400,
        )
    if margin is None:
        return (
            render_template(
                "imports.html",
                **_imports_context("마진율은 0 이상 1 미만이어야 합니다."),
            ),
            400,
        )

    conn = _db()
    create_crawl_job(
        conn,
        source="search",
        search_url=search_url,
        category_code=category_code,
        margin=margin,
    )
    flash("검색 수집 작업을 등록했습니다.")
    return redirect(url_for("main.imports"))


@bp.post("/imports/xlsx")
@login_required
def imports_xlsx_submit():
    upload = request.files.get("file")
    filename = (upload.filename or "") if upload is not None else ""
    if not filename.lower().endswith(".xlsx"):
        return (
            render_template(
                "imports.html",
                **_imports_context("엑셀(.xlsx) 파일을 선택해 주세요."),
            ),
            400,
        )

    category_code = (request.form.get("category_code") or "").strip()
    margin = _job_margin(request.form.get("margin"))
    if not category_code:
        return (
            render_template(
                "imports.html",
                **_imports_context("카테고리 코드를 입력해 주세요."),
            ),
            400,
        )
    if margin is None:
        return (
            render_template(
                "imports.html",
                **_imports_context("마진율은 0 이상 1 미만이어야 합니다."),
            ),
            400,
        )

    upload_root = Path(current_app.config["UPLOAD_ROOT"])
    upload_root.mkdir(parents=True, exist_ok=True)
    target = upload_root / f"{uuid.uuid4().hex}.xlsx"

    try:
        upload.save(target)
        create_crawl_job(
            _db(),
            source="xlsx",
            xlsx_path=str(target),
            category_code=category_code,
            margin=margin,
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise

    flash("엑셀 가져오기 작업을 등록했습니다.")
    return redirect(url_for("main.imports"))


@bp.post("/imports/<int:job_id>/retry")
@login_required
def imports_retry(job_id: int):
    conn = _db()
    job = get_job(conn, job_id)
    if job is None:
        abort(404)

    if job["source"] != "search":
        flash(
            "엑셀 작업은 원본 파일이 삭제되어 재시도할 수 없습니다. "
            "파일을 다시 업로드해 주세요.",
            "error",
        )
        return redirect(url_for("main.imports"))

    if job["status"] not in ("failed", "interrupted"):
        flash("실패한 검색 작업만 재시도할 수 있습니다.", "error")
        return redirect(url_for("main.imports"))

    create_crawl_job(
        conn,
        source="search",
        search_url=job["search_url"],
        category_code=job["category_code"],
        margin=job["margin"],
    )
    flash("검색 수집 작업을 다시 등록했습니다.")
    return redirect(url_for("main.imports"))


@bp.get("/imports/<int:job_id>/status")
@login_required
def imports_status(job_id: int):
    job = get_job(_db(), job_id)
    if job is None:
        abort(404)
    return jsonify(
        {
            "id": job["id"],
            "status": job["status"],
            "source": job["source"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "finished_at": job["finished_at"],
            "page_count": job["page_count"],
            "row_count": job["row_count"],
            "inserted_count": job["inserted_count"],
            "updated_count": job["updated_count"],
            "skipped_count": job["skipped_count"],
            "error": job["error"],
        }
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _upload_basename(filename: str) -> str:
    return (filename or "").replace("\\", "/").rsplit("/", 1)[-1]


def _reference_context(conn) -> dict:
    return {
        "original_name": get_setting(conn, "reference_original_name"),
        "uploaded_at": get_setting(conn, "reference_uploaded_at"),
        "sha256": get_setting(conn, "reference_sha256"),
        "exists": Path(current_app.config["REFERENCE_PATH"]).is_file(),
    }


COMMISSION_FALLBACK = {
    "commission_gmarket": 12.0,
    "commission_smartstore": 6.0,
    "commission_coupang": 10.0,
}

COMMISSION_LABELS = {
    "commission_gmarket": "지마켓",
    "commission_smartstore": "스마트스토어",
    "commission_coupang": "쿠팡",
}


def _setting_float(conn, key: str, fallback: float) -> float:
    raw = get_setting(conn, key)
    if raw is None:
        return fallback
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def _commission_defaults(conn) -> dict:
    return {
        key: _setting_float(conn, key, fallback)
        for key, fallback in COMMISSION_FALLBACK.items()
    }


def _exports_context(error=None) -> dict:
    conn = _db()
    return {
        "reference": _reference_context(conn),
        "exports": list_exports(current_app.config["EXPORT_ROOT"]),
        "options": list(PRODUCT_CODE_META),
        "default_option": "기타재화[35]",
        "commission_defaults": _commission_defaults(conn),
        "error": error,
    }


COMPARE_SORTS = ("price", "unit_price", "sale_price")

SALE_MARKETS = (
    ("commission_gmarket", "지마켓"),
    ("commission_smartstore", "스마트스토어"),
    ("commission_coupang", "쿠팡"),
)

SETTINGS_KEYS = (
    "default_category_code",
    "default_margin",
    "commission_gmarket",
    "commission_smartstore",
    "commission_coupang",
)


def _format_money(value) -> str:
    if value is None:
        return "-"
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def _compare_items(conn) -> list[dict]:
    ensure_default_settings(conn)
    commissions = _commission_defaults(conn)
    items = []
    for row in list_compare_rows(conn):
        unit = unit_price(
            row["market_price"], row["capacity_per_unit"], row["bundle_qty"]
        )
        sales = []
        for key, label in SALE_MARKETS:
            value = final_sale_price(
                row["market_price"],
                row["margin_rate"],
                commissions[key],
            )
            sales.append(
                {
                    "key": key,
                    "label": label,
                    "value": value,
                    "display": _format_money(value),
                }
            )
        items.append(
            {
                "id": row["id"],
                "listing_id": row["listing_id"],
                "name": row["name"],
                "image_url": row["image_url"],
                "brand": row["brand"],
                "market_price": row["market_price"],
                "market_price_display": _format_money(row["market_price"]),
                "margin_rate": row["margin_rate"],
                "unit_value": unit[0] if unit is not None else None,
                "unit_label": unit[1] if unit is not None else "",
                "unit_display": (
                    _format_money(unit[0]) if unit is not None else "-"
                ),
                "sales": sales,
                "sale_sort": sales[0]["value"] if sales else None,
            }
        )
    return items


@bp.get("/compare")
@login_required
def compare():
    sort = request.args.get("sort") or "price"
    if sort not in COMPARE_SORTS:
        sort = "price"
    items = _compare_items(_db())
    if sort == "unit_price":
        items.sort(
            key=lambda item: (
                item["unit_value"] is None,
                item["unit_value"] or 0,
                item["listing_id"],
            )
        )
    elif sort == "sale_price":
        items.sort(
            key=lambda item: (
                item["sale_sort"] is None,
                item["sale_sort"] or 0,
                item["listing_id"],
            )
        )
    else:
        items.sort(key=lambda item: (item["market_price"], item["listing_id"]))
    return render_template(
        "compare.html", items=items, sort=sort, sorts=COMPARE_SORTS
    )


def _settings_context(conn, error=None) -> dict:
    ensure_default_settings(conn)
    return {
        "settings": {key: get_setting(conn, key) for key in SETTINGS_KEYS},
        "options": list(PRODUCT_CODE_META),
        "export_ttl_hours": current_app.config["EXPORT_TTL_HOURS"],
        "reference": _reference_context(conn),
        "error": error,
    }


@bp.get("/settings")
@login_required
def settings():
    return render_template("settings.html", **_settings_context(_db()))


@bp.post("/settings")
@login_required
def settings_submit():
    conn = _db()
    ensure_default_settings(conn)
    current = {key: get_setting(conn, key) for key in SETTINGS_KEYS}

    category = (request.form.get("default_category_code") or "").strip()
    category = category or current["default_category_code"]
    try:
        meta_for_option(category)
    except ValueError as exc:
        return (
            render_template("settings.html", **_settings_context(conn, str(exc))),
            400,
        )

    raw_margin = (request.form.get("default_margin") or "").strip()
    if raw_margin:
        try:
            margin = float(raw_margin)
        except (TypeError, ValueError):
            margin = None
        if margin is None or not 0 <= margin <= 1:
            return (
                render_template(
                    "settings.html",
                    **_settings_context(
                        conn, "마진율은 0 이상 1 이하여야 합니다."
                    ),
                ),
                400,
            )
    else:
        margin = _setting_float(conn, "default_margin", 0.15)

    commissions = {}
    for key in (
        "commission_gmarket",
        "commission_smartstore",
        "commission_coupang",
    ):
        raw = (request.form.get(key) or "").strip()
        if raw:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = None
            if value is None or not 0 <= value < 100:
                return (
                    render_template(
                        "settings.html",
                        **_settings_context(
                            conn,
                            "수수료는 0 이상 100 미만의 숫자여야 합니다.",
                        ),
                    ),
                    400,
                )
        else:
            value = _setting_float(conn, key, COMMISSION_FALLBACK[key])
        commissions[key] = str(value)

    set_settings(
        conn,
        {
            "default_category_code": category,
            "default_margin": str(margin),
            **commissions,
        },
    )
    flash("설정을 저장했습니다.")
    return redirect(url_for("main.settings"))


def _restore_reference(path: Path, previous: bytes | None) -> None:
    try:
        if previous is None:
            path.unlink(missing_ok=True)
            return
        temporary = path.with_name(f"{path.name}.restore-{uuid.uuid4().hex}")
        try:
            temporary.write_bytes(previous)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    except OSError:
        current_app.logger.exception("failed to restore reference workbook")


@bp.get("/exports")
@login_required
def exports():
    return render_template("exports.html", **_exports_context())


@bp.post("/exports/reference")
@login_required
def exports_reference_submit():
    upload = request.files.get("file")
    original_name = _upload_basename(
        upload.filename if upload is not None else ""
    )
    if not original_name.lower().endswith(".xlsx"):
        return (
            render_template(
                "exports.html",
                **_exports_context("엑셀(.xlsx) 파일을 선택해 주세요."),
            ),
            400,
        )

    upload_root = Path(current_app.config["UPLOAD_ROOT"])
    upload_root.mkdir(parents=True, exist_ok=True)
    temporary = upload_root / f"reference-{uuid.uuid4().hex}.xlsx"
    reference_path = Path(current_app.config["REFERENCE_PATH"])

    try:
        previous = reference_path.read_bytes() if reference_path.is_file() else None
    except OSError:
        return (
            render_template(
                "exports.html",
                **_exports_context(
                    "기존 기준 엑셀을 읽을 수 없어 교체하지 못했습니다."
                ),
            ),
            400,
        )

    try:
        upload.save(temporary)
        info = save_reference(temporary, reference_path)
        set_settings(
            _db(),
            {
                "reference_original_name": original_name,
                "reference_uploaded_at": _utc_now(),
                "reference_sha256": info["sha256"],
            },
        )
    except (ValueError, OSError, sqlite3.Error) as exc:
        _restore_reference(reference_path, previous)
        if isinstance(exc, ValueError):
            message = f"기준 엑셀을 저장하지 못했습니다: {exc}"
        else:
            current_app.logger.exception("reference upload failed")
            message = "기준 엑셀을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요."
        return (
            render_template("exports.html", **_exports_context(message)),
            400,
        )
    finally:
        temporary.unlink(missing_ok=True)

    flash("기준 엑셀을 저장했습니다.")
    return redirect(url_for("main.exports"))


def _form_commission(conn):
    defaults = _commission_defaults(conn)
    commission = {}
    for field, label in COMMISSION_LABELS.items():
        raw = (request.form.get(field) or "").strip()
        if not raw:
            commission[label] = defaults[field]
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not 0 <= value < 100:
            return None
        commission[label] = value
    return commission


@bp.post("/exports")
@login_required
def exports_submit():
    option = (request.form.get("option") or "").strip()
    try:
        meta_for_option(option)
    except ValueError as exc:
        return (
            render_template(
                "exports.html", **_exports_context(str(exc))
            ),
            400,
        )

    run_date = None
    raw_date = (request.form.get("run_date") or "").strip()
    if raw_date:
        try:
            run_date = date.fromisoformat(raw_date)
        except ValueError:
            return (
                render_template(
                    "exports.html",
                    **_exports_context("날짜 형식이 올바르지 않습니다."),
                ),
                400,
            )

    commission = _form_commission(_db())
    if commission is None:
        return (
            render_template(
                "exports.html",
                **_exports_context(
                    "수수료는 0 이상 100 미만의 숫자여야 합니다."
                ),
            ),
            400,
        )

    reference_path = Path(current_app.config["REFERENCE_PATH"])
    if not reference_path.is_file():
        flash("기준 엑셀이 없어 엑셀을 생성할 수 없습니다.", "error")
        return redirect(url_for("main.exports"))

    try:
        export_to_dir(
            current_app.config["DATABASE"],
            reference_path,
            current_app.config["EXPORT_ROOT"],
            option=option,
            run_date=run_date,
            coupang_single=bool(request.form.get("coupang_single")),
            commission=commission,
        )
    except ValueError as exc:
        flash(f"엑셀을 생성하지 못했습니다: {exc}", "error")
        return redirect(url_for("main.exports"))
    except Exception:  # noqa: BLE001 - route must not leak a traceback
        current_app.logger.exception("export generation failed")
        flash(
            "엑셀을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            "error",
        )
        return redirect(url_for("main.exports"))

    flash("엑셀을 생성했습니다.")
    return redirect(url_for("main.exports"))


@bp.get("/exports/<export_id>/<filename>")
@login_required
def export_download(export_id: str, filename: str):
    if filename not in ("setting", "single", "general"):
        abort(404)
    if not export_id or export_id in (".", ".."):
        abort(404)
    if "/" in export_id or "\\" in export_id or ".." in export_id:
        abort(404)

    directory = Path(current_app.config["EXPORT_ROOT"]) / export_id
    try:
        if not directory.is_dir():
            abort(404)
        target = export_file(directory, filename)
    except OSError:
        abort(404)
    if target is None:
        abort(404)
    return send_from_directory(
        str(directory.resolve()),
        target.name,
        as_attachment=True,
        download_name=target.name,
    )


@bp.post("/exports/<export_id>/delete")
@login_required
def export_delete(export_id: str):
    if not delete_export(current_app.config["EXPORT_ROOT"], export_id):
        abort(404)
    flash("export를 삭제했습니다.")
    return redirect(url_for("main.exports"))

