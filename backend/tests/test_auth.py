from fastapi.testclient import TestClient

from app.dependencies import get_auth_service
from app.main import app
from app.repositories.user_repository import InMemoryUserRepository
from app.services.auth_service import AuthService


client = TestClient(app)


def make_service() -> tuple[AuthService, InMemoryUserRepository]:
    repository = InMemoryUserRepository()
    service = AuthService(
        repository,
        secret_key="test-secret-key-which-is-longer-than-32-bytes",
    )
    return service, repository


def test_signup_login_and_me() -> None:
    service, repository = make_service()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        signup = client.post(
            "/auth/signup",
            json={"username": "LocalUser", "password": "password123"},
        )
        assert signup.status_code == 201
        assert signup.json()["username"] == "localuser"
        assert "password" not in signup.json()

        login = client.post(
            "/auth/login",
            json={"username": "LocalUser", "password": "password123"},
        )
        assert login.status_code == 200
        assert login.json()["token_type"] == "bearer"

        me = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["user_id"] == signup.json()["user_id"]

        stored = __import__("asyncio").run(repository.get_by_username("localuser"))
        assert stored is not None
        assert stored.password_hash != "password123"
    finally:
        app.dependency_overrides.clear()


def test_duplicate_username_uses_common_error_contract() -> None:
    service, _ = make_service()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        payload = {"username": "localuser", "password": "password123"}
        assert client.post("/auth/signup", json=payload).status_code == 201
        response = client.post("/auth/signup", json=payload)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "http_409"
    finally:
        app.dependency_overrides.clear()


def test_invalid_login_and_missing_token_are_rejected() -> None:
    service, _ = make_service()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        response = client.post(
            "/auth/login",
            json={"username": "missing", "password": "wrongpass123"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "http_401"
        assert response.headers["www-authenticate"] == "Bearer"

        me = client.get("/auth/me")
        assert me.status_code == 401
    finally:
        app.dependency_overrides.clear()
