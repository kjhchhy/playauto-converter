import functools
import hmac
import secrets

from flask import redirect, request, session, url_for
from werkzeug.security import check_password_hash


def check_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return check_password_hash(password_hash, password)
    except (TypeError, ValueError):
        return False


def csrf_token(session) -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf(session, token: str | None) -> bool:
    expected = session.get("_csrf_token")
    if not expected or not token:
        return False
    return hmac.compare_digest(str(expected), str(token))


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("main.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped
