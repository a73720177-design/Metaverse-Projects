"""각 팀 서비스를 수정하지 않고 연결 가능 여부만 확인하는 공통 점검 도구."""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def check_timeout() -> float:
    raw_value = os.getenv("CHECK_TIMEOUT_SECONDS", "5").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError("CHECK_TIMEOUT_SECONDS must be a number.") from exc
    if value <= 0:
        raise ValueError("CHECK_TIMEOUT_SECONDS must be greater than zero.")
    return value


def check_http(name: str, url: str, path: str, timeout: float) -> dict[str, object]:
    target = f"{url.rstrip('/')}{path}"
    try:
        request = Request(target, headers={"User-Agent": "Metaverse-Integration-Check"})
        with urlopen(request, timeout=timeout) as response:
            return {
                "service": name,
                "status": "ok" if response.status < 400 else "error",
                "target": target,
                "http_status": response.status,
            }
    except HTTPError as exc:
        return {
            "service": name,
            "status": "error",
            "target": target,
            "http_status": exc.code,
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "service": name,
            "status": "unavailable",
            "target": target,
            "detail": str(exc.reason if isinstance(exc, URLError) else exc),
        }


def check_tcp(name: str, host: str, port: int, timeout: float) -> dict[str, object]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"service": name, "status": "ok", "target": f"{host}:{port}"}
    except OSError as exc:
        return {
            "service": name,
            "status": "unavailable",
            "target": f"{host}:{port}",
            "detail": str(exc),
        }


def parse_endpoint(value: str, default_port: int) -> tuple[str, int]:
    endpoint = value.strip()
    if not endpoint:
        raise ValueError("endpoint is empty")
    parsed = urlparse(endpoint if "://" in endpoint else f"//{endpoint}")
    if not parsed.hostname:
        raise ValueError(f"invalid endpoint: {value}")
    return parsed.hostname, parsed.port or default_port


def required_services() -> set[str]:
    raw_value = os.getenv(
        "REQUIRED_SERVICES",
        "frontend,backend,llm,ollama,postgresql,minio",
    )
    return {item.strip().lower() for item in raw_value.split(",") if item.strip()}


def main() -> int:
    load_env(ROOT / ".env")
    try:
        timeout = check_timeout()
    except ValueError as exc:
        print(json.dumps({"configuration_error": str(exc)}, ensure_ascii=False))
        return 2

    checks = [
        check_http(
            "frontend", os.getenv("FRONTEND_URL", "http://localhost:5173"), "/", timeout
        ),
        check_http(
            "backend", os.getenv("BACKEND_URL", "http://localhost:8000"), "/health", timeout
        ),
        check_http(
            "llm", os.getenv("LLM_URL", "http://localhost:8001"), "/health", timeout
        ),
        check_http(
            "ollama",
            os.getenv("OLLAMA_URL", "http://localhost:11434"),
            "/api/tags",
            timeout,
        ),
    ]

    db_host = os.getenv("DB_HOST", "").strip()
    if db_host:
        try:
            db_port = int(os.getenv("DB_PORT", "5432"))
            checks.append(check_tcp("postgresql", db_host, db_port, timeout))
        except ValueError:
            checks.append(
                {
                    "service": "postgresql",
                    "status": "invalid_config",
                    "detail": "DB_PORT must be an integer.",
                }
            )
    else:
        checks.append(
            {
                "service": "postgresql",
                "status": "not_configured",
                "detail": "integration/.env의 DB_HOST 설정이 필요합니다.",
            }
        )

    minio_endpoint = os.getenv("MINIO_ENDPOINT", "").strip()
    if minio_endpoint:
        try:
            minio_host, minio_port = parse_endpoint(minio_endpoint, 9000)
            checks.append(check_tcp("minio", minio_host, minio_port, timeout))
        except ValueError as exc:
            checks.append({"service": "minio", "status": "invalid_config", "detail": str(exc)})
    else:
        checks.append(
            {
                "service": "minio",
                "status": "not_configured",
                "detail": "integration/.env의 MINIO_ENDPOINT 설정이 필요합니다.",
            }
        )

    required = required_services()
    failed_required = [
        item for item in checks if item["service"] in required and item["status"] != "ok"
    ]
    print(
        json.dumps(
            {
                "status": "ok" if not failed_required else "error",
                "required_services": sorted(required),
                "services": checks,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failed_required else 0


if __name__ == "__main__":
    sys.exit(main())
