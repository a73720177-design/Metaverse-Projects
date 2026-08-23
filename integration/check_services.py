"""각 팀 서비스를 수정하지 않고 연결 가능 여부만 확인하는 공통 점검 도구."""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
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


def check_http(name: str, url: str, path: str) -> dict[str, object]:
    target = f"{url.rstrip('/')}{path}"
    try:
        request = Request(target, headers={"User-Agent": "Metaverse-Integration-Check"})
        with urlopen(request, timeout=5) as response:
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


def check_tcp(name: str, host: str, port: int) -> dict[str, object]:
    try:
        with socket.create_connection((host, port), timeout=5):
            return {"service": name, "status": "ok", "target": f"{host}:{port}"}
    except OSError as exc:
        return {
            "service": name,
            "status": "unavailable",
            "target": f"{host}:{port}",
            "detail": str(exc),
        }


def main() -> int:
    load_env(ROOT / ".env")

    checks = [
        check_http("frontend", os.getenv("FRONTEND_URL", "http://localhost:5173"), "/"),
        check_http("backend", os.getenv("BACKEND_URL", "http://localhost:8000"), "/health"),
        check_http("llm", os.getenv("LLM_URL", "http://localhost:8001"), "/health"),
        check_http("ollama", os.getenv("OLLAMA_URL", "http://localhost:11434"), "/api/tags"),
    ]

    db_host = os.getenv("DB_HOST", "").strip()
    if db_host:
        checks.append(check_tcp("postgresql", db_host, int(os.getenv("DB_PORT", "5432"))))
    else:
        checks.append(
            {
                "service": "postgresql",
                "status": "not_configured",
                "detail": "integration/.env의 DB_HOST 설정이 필요합니다.",
            }
        )

    print(json.dumps({"services": checks}, ensure_ascii=False, indent=2))
    required = {"backend", "llm"}
    failed_required = [
        item for item in checks if item["service"] in required and item["status"] != "ok"
    ]
    return 1 if failed_required else 0


if __name__ == "__main__":
    sys.exit(main())
