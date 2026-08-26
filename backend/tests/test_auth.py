from fastapi.testclient import TestClient

from app.dependencies import get_auth_service
from app.main import app
from app.repositories.user_repository import InMemoryUserRepository
from app.services.auth_service import AuthService


client = TestClient(app)


def make_service() -> tuple[AuthService, InMemoryUserRepository]:
    repository = InMemoryUserRepository()
    service = AuthService(repository, secret_key="test-secret-key-which-is-longer-than-32-characters")
    return service, repository


def test_signup_login_and_me() -> None:
    service, repository = make_service()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        signup = client.post(
            "/auth/signup", json={"username": "LocalUser", "password": "password123"}
        )
        assert signup.status_code == 201
        assert signup.json()["username"] == "localuser"
        assert "password" not in signup.json()

        stored = __import__("asyncio").run(repository.get_by_username("localuser"))
        assert stored is not None
        assert stored.password_hash != "password123"

        login = client.post(
            "/auth/login", json={"username": "LocalUser", "password": "password123"}
        )
        assert login.status_code == 200
        token = login.json()["access_token"]

        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["user_id"] == signup.json()["user_id"]
    finally:
        app.dependency_overrides.clear()


def test_duplicate_username_is_rejected() -> None:
    service, _ = make_service()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        payload = {"username": "localuser", "password": "password123"}
        assert client.post("/auth/signup", json=payload).status_code == 201
        assert client.post("/auth/signup", json=payload).status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_wrong_password_is_rejected() -> None:
    service, _ = make_service()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        assert client.post(
            "/auth/signup", json={"username": "localuser", "password": "password123"}
        ).status_code == 201
        response = client.post(
            "/auth/login", json={"username": "localuser", "password": "wrongpass123"}
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
