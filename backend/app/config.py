import os
from pathlib import Path
from urllib.parse import urlsplit

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

# Hamachi와 사설 LAN에서 공유하는 Vite 개발/preview 서버만 허용합니다.
DEFAULT_FRONTEND_ORIGIN_REGEX = (
    r"^http://(?:"
    r"25(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}|"
    r"10(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}|"
    r"192\.168(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){2}"
    r"):(?:4173|5173)$"
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


def get_rag_max_context_chars() -> int:
    return _get_positive_int("RAG_MAX_CONTEXT_CHARS", 4000)


def get_practice_max_concurrent_personas() -> int:
    return _get_positive_int("PRACTICE_MAX_CONCURRENT_PERSONAS", 1)


def get_rag_mode() -> str:
    return _get_choice("RAG_MODE", "lexical", {"lexical", "vector"})


def get_embedding_model() -> str:
    return os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3:latest").strip() or "bge-m3:latest"


def get_embedding_url() -> str:
    return os.getenv("OLLAMA_EMBEDDING_URL", "http://127.0.0.1:11434").strip().rstrip("/")


def get_embedding_dimension() -> int:
    return _get_positive_int("EMBEDDING_DIMENSION", 1024)


def get_embedding_timeout_seconds() -> int:
    return _get_positive_int("EMBEDDING_TIMEOUT_SECONDS", 8)


def get_vector_rag_candidate_k() -> int:
    return _get_positive_int("VECTOR_RAG_CANDIDATE_K", 12)


def get_vector_rag_final_k() -> int:
    return _get_positive_int("VECTOR_RAG_FINAL_K", 6)


def get_vector_rag_max_distance() -> float:
    value = os.getenv("VECTOR_RAG_MAX_DISTANCE", "0.65").strip()
    try:
        distance = float(value)
    except ValueError as exc:
        raise RuntimeError("VECTOR_RAG_MAX_DISTANCE must be a number.") from exc
    if not 0 < distance <= 2:
        raise RuntimeError("VECTOR_RAG_MAX_DISTANCE must be greater than 0 and at most 2.")
    return distance


def get_jwt_secret_key() -> str:
    secret_key = os.getenv("JWT_SECRET_KEY", "").strip()
    if len(secret_key.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET_KEY must contain at least 32 bytes.")
    return secret_key


def get_jwt_access_token_expire_minutes() -> int:
    value = os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60").strip()
    try:
        minutes = int(value)
    except ValueError as exc:
        raise RuntimeError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be an integer.") from exc
    if minutes < 1:
        raise RuntimeError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be at least 1.")
    return minutes


def _get_positive_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if parsed < 1:
        raise RuntimeError(f"{name} must be at least 1.")
    return parsed


def _get_unit_interval_float(name: str, default: float) -> float:
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = float(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number.") from exc
    if not 0 <= parsed <= 1:
        raise RuntimeError(f"{name} must be between 0 and 1.")
    return parsed


def get_login_rate_limit_attempts() -> int:
    return _get_positive_int("LOGIN_RATE_LIMIT_ATTEMPTS", 5)


def get_login_rate_limit_window_seconds() -> int:
    return _get_positive_int("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 60)


def get_chat_history_turns() -> int:
    return _get_positive_int("CHAT_HISTORY_TURNS", 6)


def get_chunk_cache_size() -> int:
    return _get_positive_int("CHUNK_CACHE_SIZE", 32)


def get_grounding_mode() -> str:
    return _get_choice("GROUNDING_MODE", "off", {"off", "annotate", "strict"})


def get_grounding_threshold() -> float:
    return _get_unit_interval_float("GROUNDING_THRESHOLD", 0.35)


def get_grounding_min_score() -> float:
    return _get_unit_interval_float("GROUNDING_MIN_SCORE", 0.5)


def validate_runtime_contract() -> None:
    """서로 호환되지 않는 Backend·DB 설정을 서버 시작 시 거부한다."""

    repository_mode = get_repository_mode()
    rag_mode = get_rag_mode()
    if repository_mode == "postgres" and not os.getenv("DATABASE_URL", "").strip():
        raise RuntimeError(
            "REPOSITORY_MODE=postgres requires DATABASE_URL."
        )
    if repository_mode == "postgres":
        try:
            target = urlsplit(os.environ["DATABASE_URL"].strip())
            valid_url = (
                target.scheme in {"postgres", "postgresql", "postgresql+asyncpg"}
                and bool(target.hostname)
                and bool(target.path.lstrip("/"))
                and (target.port is None or 0 < target.port <= 65535)
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            raise RuntimeError("DATABASE_URL must be a valid PostgreSQL URL with a host and database name.")
    if rag_mode == "vector" and repository_mode != "postgres":
        raise RuntimeError(
            "RAG_MODE=vector requires REPOSITORY_MODE=postgres."
        )
    if repository_mode == "postgres" and get_embedding_dimension() != 1024:
        raise RuntimeError(
            "REPOSITORY_MODE=postgres requires EMBEDDING_DIMENSION=1024 to match migration 009."
        )
    if rag_mode == "vector" and get_db_auto_create():
        raise RuntimeError(
            "DB_AUTO_CREATE cannot install migration 009; apply numbered migrations "
            "and set DB_AUTO_CREATE=false."
        )


def get_chat_output_token_budgets() -> dict[str, int]:
    budgets = {
        "concise": _get_positive_int("CHAT_OUTPUT_TOKENS_CONCISE", 512),
        "standard": _get_positive_int("CHAT_OUTPUT_TOKENS_STANDARD", 1024),
        "detailed": _get_positive_int("CHAT_OUTPUT_TOKENS_DETAILED", 1024),
    }
    maximum = _get_positive_int("CHAT_OUTPUT_TOKENS_MAX", 1024)
    if any(value > maximum for value in budgets.values()):
        raise RuntimeError("Chat output token budgets must not exceed CHAT_OUTPUT_TOKENS_MAX.")
    return budgets
