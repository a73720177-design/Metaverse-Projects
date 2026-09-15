import asyncio
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.controllers.chat_controller import _encode_sse
from app.error_handlers import register_error_handlers
from app.models.user import UserCredentials


@pytest.fixture
def client():
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173'],
                       expose_headers=['X-Request-ID', 'Retry-After'])

    @app.post('/credentials')
    def credentials(body: UserCredentials):
        return {'ok': True}

    @app.get('/bad-response')
    def bad_response() -> dict[str, str]:
        return {'contract': {'secret': 'DO_NOT_EXPOSE'}}

    @app.get('/unexpected')
    def unexpected():
        raise RuntimeError('DO_NOT_EXPOSE')

    @app.get('/limited')
    def limited():
        raise HTTPException(429, 'Too many requests', headers={'Retry-After': '60'})

    @app.get('/database/{sqlstate}')
    def database(sqlstate: str):
        exc = RuntimeError('DO_NOT_EXPOSE')
        exc.sqlstate = sqlstate
        raise DBAPIError('SELECT secret', {'password': 'DO_NOT_EXPOSE'}, exc)

    with TestClient(app) as test_client:
        yield test_client


def test_validation_fields_do_not_echo_password(client):
    response = client.post('/credentials', json={'username': '!', 'password': 'secret'})
    error = response.json()['error']
    assert response.status_code == 422
    assert error['code'] == 'validation_error'
    assert len(error['fields']) == 2
    assert 'secret' not in response.text
    assert all('input' not in field and 'ctx' not in field for field in error['fields'])
    assert error['request_id'] == response.headers['x-request-id']


@pytest.mark.parametrize(('path', 'code'), [('/bad-response', 'response_validation_error'), ('/unexpected', 'internal_server_error')])
def test_server_errors_are_json_with_cors_and_trace_id(client, path, code):
    response = client.get(path, headers={'Origin': 'http://localhost:5173'})
    assert response.status_code == 500
    assert response.json()['error']['code'] == code
    assert response.json()['error']['request_id'] == response.headers['x-request-id']
    assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
    assert 'DO_NOT_EXPOSE' not in response.text


@pytest.mark.parametrize(('state', 'code'), [('25006', 'database_read_only'), ('42703', 'database_schema_mismatch'), ('42P01', 'database_schema_mismatch'), ('08006', 'database_unavailable')])
def test_database_errors_classify_without_sql_or_credentials(client, state, code):
    response = client.get('/database/' + state)
    assert response.status_code == 503
    assert response.json()['error']['code'] == code
    assert 'DO_NOT_EXPOSE' not in response.text
    assert 'SELECT' not in response.text


def test_retry_headers_and_request_ids_are_available_to_frontend(client):
    response = client.get('/limited', headers={'Origin': 'http://localhost:5173'})
    assert response.headers['retry-after'] == '60'
    assert 'Retry-After' in response.headers['access-control-expose-headers']
    assert 'X-Request-ID' in response.headers['access-control-expose-headers']


def test_unexpected_sse_failure_has_safe_error_event():
    async def check():
        async def upstream():
            yield {'event': 'token', 'data': {'token': 'partial'}}
            raise RuntimeError('DO_NOT_EXPOSE')
        blocks = [block async for block in _encode_sse(upstream(), request_id='stream-1')]
        error = json.loads(blocks[-1].split('data: ', 1)[1])
        assert error['code'] == 'stream_error'
        assert error['request_id'] == 'stream-1'
        assert 'DO_NOT_EXPOSE' not in ''.join(blocks)
    asyncio.run(check())


def test_real_db_health_accepts_nested_contract(monkeypatch):
    from unittest.mock import AsyncMock
    from app import main

    contract = {'status': 'ok', 'latest_migration': '011', 'missing': {}}
    monkeypatch.setattr(main, 'get_repository_mode', lambda: 'postgres')
    monkeypatch.setattr(main, 'check_db', AsyncMock())
    monkeypatch.setattr(main, 'inspect_db_contract', AsyncMock(return_value=contract))
    response = TestClient(main.app).get('/health/db')
    assert response.status_code == 200
    assert response.json()['contract'] == contract


def test_failures_never_log_exception_contents_or_tracebacks(client, caplog):
    client.get('/unexpected')
    client.get('/database/08006')
    assert 'DO_NOT_EXPOSE' not in caplog.text
    assert 'SELECT secret' not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_post_start_failure_closes_without_reraising_sensitive_exception(caplog):
    from app.error_handlers import RequestErrorMiddleware
    async def run():
        sent = []
        async def inner(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'partial', 'more_body': True})
            raise RuntimeError('DO_NOT_EXPOSE')
        async def send(message):
            sent.append(message)
        await RequestErrorMiddleware(inner)({'type': 'http', 'state': {}}, None, send)
        assert sent[-1]['more_body'] is False
    asyncio.run(run())
    assert 'DO_NOT_EXPOSE' not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
