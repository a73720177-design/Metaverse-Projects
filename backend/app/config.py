import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")


DEFAULT_FRONTEND_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
)

# Hamachi에서 공유하는 Vite 개발 서버(5173)와 preview 서버(4173)만 허용합니다.
DEFAULT_FRONTEND_ORIGIN_REGEX = (
    r"^http://25(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}:(?:4173|5173)$"
)


def get_frontend_origins() -> list[str]:
    """Return allowed browser origins from a comma-separated environment value."""
    configured_origins = os.getenv("FRONTEND_ORIGINS")
    if configured_origins is None:
        return list(DEFAULT_FRONTEND_ORIGINS)

    return [
        origin.strip().rstrip("/")
        for origin in configured_origins.split(",")
        if origin.strip()
    ]


def get_frontend_origin_regex() -> str | None:
    """Return an optional CORS regex for shared development servers."""
    configured_regex = os.getenv("FRONTEND_ORIGIN_REGEX")
    if configured_regex is None:
        return DEFAULT_FRONTEND_ORIGIN_REGEX

    return configured_regex.strip() or None


def _get_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise RuntimeError(f"{name} must be one of: {allowed}")
    return value


def get_repository_mode() -> str:
    return _get_choice("REPOSITORY_MODE", "memory", {"memory", "postgres"})


def get_object_storage_mode() -> str:
    return _get_choice("OBJECT_STORAGE_MODE", "local", {"local", "minio"})


def get_db_auto_create() -> bool:
    return os.getenv("DB_AUTO_CREATE", "false").strip().lower() in {"1", "true", "yes"}


def get_max_upload_size_bytes() -> int:
    value = os.getenv("MAX_UPLOAD_SIZE_MB", "25").strip()
    try:
        megabytes = int(value)
    except ValueError as exc:
        raise RuntimeError("MAX_UPLOAD_SIZE_MB must be an integer.") from exc
    if megabytes < 1:
        raise RuntimeError("MAX_UPLOAD_SIZE_MB must be at least 1.")
    return megabytes * 1024 * 1024
