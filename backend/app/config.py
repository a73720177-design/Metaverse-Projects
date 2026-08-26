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


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("backend/.env의 DATABASE_URL을 설정해야 합니다.")
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


def get_jwt_secret_key() -> str:
    secret_key = os.getenv("JWT_SECRET_KEY", "").strip()
    if len(secret_key) < 32:
        raise RuntimeError("backend/.env의 JWT_SECRET_KEY를 32자 이상으로 설정해야 합니다.")
    return secret_key


def get_jwt_access_token_expire_minutes() -> int:
    value = os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60").strip()
    try:
        minutes = int(value)
    except ValueError as exc:
        raise RuntimeError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES는 정수여야 합니다.") from exc
    if minutes <= 0:
        raise RuntimeError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES는 1 이상이어야 합니다.")
    return minutes
