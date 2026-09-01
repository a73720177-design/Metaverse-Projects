from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from app.dependencies import (
    get_current_user,
    get_document_repository,
    get_object_storage,
)
from app.main import app
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.user import UserResponse
from app.repositories.document_repository import InMemoryDocumentRepository


OWNER = UserResponse(
    user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    username="owner",
    created_at=datetime.now(timezone.utc),
)
OTHER_USER = UserResponse(
    user_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    username="other",
    created_at=datetime.now(timezone.utc),
)


class FakeStorage:
    bucket = "test"

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def upload(self, source, object_key, content_type=None) -> None:
        pass

    async def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


def test_document_list_get_delete_and_owner_isolation() -> None:
    repository = InMemoryDocumentRepository()
    storage = FakeStorage()
    document = DocumentParseResponse(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        filename="source.pdf",
        document_type="pdf",
        saved_path=Path("11111111-1111-1111-1111-111111111111/original.pdf"),
        sections=[DocumentSection(index=1, text="verification text")],
        full_text="verification text",
    )

    import asyncio

    asyncio.run(repository.save(document, OWNER.user_id))
    app.dependency_overrides[get_document_repository] = lambda: repository
    app.dependency_overrides[get_object_storage] = lambda: storage
    app.dependency_overrides[get_current_user] = lambda: OWNER
    client = TestClient(app)

    try:
        listed = client.get("/documents")
        assert listed.status_code == 200
        assert listed.json()[0]["document_id"] == str(document.document_id)
        assert listed.json()[0]["filename"] == "source.pdf"
        assert listed.json()[0]["section_count"] == 1
        assert listed.json()[0]["text_length"] == len("verification text")

        fetched = client.get(f"/documents/{document.document_id}")
        assert fetched.status_code == 200
        assert fetched.json()["full_text"] == "verification text"
        assert fetched.json()["section_count"] == 1
        assert fetched.json()["text_length"] == len("verification text")
        assert "saved_path" not in fetched.json()

        app.dependency_overrides[get_current_user] = lambda: OTHER_USER
        assert client.get("/documents").json() == []
        assert client.get(f"/documents/{document.document_id}").status_code == 404
        assert client.delete(f"/documents/{document.document_id}").status_code == 404

        app.dependency_overrides[get_current_user] = lambda: OWNER
        deleted = client.delete(f"/documents/{document.document_id}")
        assert deleted.status_code == 204
        assert storage.deleted == [str(document.saved_path)]
        assert client.get("/documents").json() == []
        assert client.get(f"/documents/{document.document_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()
