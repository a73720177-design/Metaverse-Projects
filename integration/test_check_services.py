from __future__ import annotations

import pytest

from integration.check_services import check_timeout, parse_endpoint, required_services


def test_parse_endpoint_accepts_host_port_and_url() -> None:
    assert parse_endpoint("localhost:9000", 9000) == ("localhost", 9000)
    assert parse_endpoint("http://127.0.0.1:9100", 9000) == ("127.0.0.1", 9100)


def test_parse_endpoint_uses_default_port() -> None:
    assert parse_endpoint("minio.local", 9000) == ("minio.local", 9000)


def test_check_timeout_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECK_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValueError, match="greater than zero"):
        check_timeout()


def test_required_services_parses_and_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUIRED_SERVICES", " Backend, LLM, minio ")
    assert required_services() == {"backend", "llm", "minio"}
