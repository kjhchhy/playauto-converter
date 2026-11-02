import os

DEFAULTS = {
    "DATABASE": "data/playauto.db",
    "REFERENCE_PATH": "data/reference/current.xlsx",
    "EXPORT_ROOT": "data/exports",
    "UPLOAD_ROOT": "data/uploads",
    "BROWSER_PROFILE": "data/browser-profile",
    "EXPORT_TTL_HOURS": 24,
    "MAX_CONTENT_LENGTH": 20 * 1024 * 1024,
    "SESSION_COOKIE_SECURE": False,
    "TESTING": False,
}

INT_KEYS = ("EXPORT_TTL_HOURS", "MAX_CONTENT_LENGTH")
BOOL_KEYS = ("SESSION_COOKIE_SECURE", "TESTING")
REQUIRED_KEYS = ("SECRET_KEY", "ADMIN_PASSWORD_HASH")


def _as_int(key, value):
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} 값이 정수가 아닙니다: {value!r}") from exc


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_config(overrides: dict | None = None) -> dict:
    config = dict(DEFAULTS)

    for key in (*REQUIRED_KEYS, *DEFAULTS):
        raw = os.environ.get(key)
        if raw is None or raw == "":
            continue
        if key in INT_KEYS:
            config[key] = _as_int(key, raw)
        elif key in BOOL_KEYS:
            config[key] = _as_bool(raw)
        else:
            config[key] = raw

    if overrides:
        config.update(overrides)

    for key in INT_KEYS:
        config[key] = _as_int(key, config[key])
    for key in BOOL_KEYS:
        config[key] = _as_bool(config[key])

    missing = [key for key in REQUIRED_KEYS if not config.get(key)]
    if missing:
        raise RuntimeError(
            "필수 환경변수가 설정되지 않았습니다: " + ", ".join(missing)
        )

    return config
