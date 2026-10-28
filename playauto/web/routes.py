import time

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .auth import check_password, csrf_token, login_required

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


def _limiter() -> LoginRateLimiter:
    return current_app.extensions["login_limiter"]


def _safe_next(target: str | None) -> str:
    if not target or not target.startswith("/") or target.startswith("//"):
        return url_for("main.dashboard")
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
