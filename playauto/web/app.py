from flask import Flask, abort, current_app, g, request, session

from playauto.db import connect, ensure_schema

from .auth import csrf_token, validate_csrf
from .config import build_config
from .routes import LoginRateLimiter, bp

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_db():
    if "db" not in g:
        conn = connect(current_app.config["DATABASE"])
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        g.db = conn
    return g.db


def close_db(exception=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(build_config(config))

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = bool(
        app.config.get("SESSION_COOKIE_SECURE")
    )

    app.teardown_appcontext(close_db)

    with app.app_context():
        ensure_schema(get_db())

    app.extensions["login_limiter"] = LoginRateLimiter()
    app.register_blueprint(bp)

    @app.before_request
    def protect_csrf():
        if request.method not in UNSAFE_METHODS:
            return None
        token = request.form.get("csrf_token") or request.headers.get(
            "X-CSRF-Token"
        )
        if not validate_csrf(session, token):
            abort(400)
        return None

    @app.context_processor
    def inject_csrf():
        return {"csrf_token": csrf_token(session)}

    return app
