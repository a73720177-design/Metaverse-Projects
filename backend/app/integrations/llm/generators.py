from typing import Any
from uuid import UUID

from app.integrations.llm.client import (
    HttpLlmClient,
    LlmServiceConnectionError,
    LlmServiceResponseError,
)
from app.integrations.llm.contracts import (
    ChatGeneratorError,
    DocumentIndexError,
    DocumentNotIndexedError,
    PersonaGeneratorError,
    ReviewGeneratorError,
)
from app.models.chat import ChatRequest
from app.models.document import DocumentParseResponse
from app.models.persona import PersonaCreateRequest, PersonaProfile


def _raise_if_not_indexed(exc: LlmServiceResponseError) -> None:
    """LLM 서비스의 409 document_not_indexed를 복구 가능한 에러로 바꿉니다."""
    if exc.status_code != 409:
        return
    detail = exc.body.get("detail") if isinstance(exc.body, dict) else None
    if not isinstance(detail, dict) or detail.get("code") != "document_not_indexed":
        return
    try:
        document_id = UUID(str(detail.get("document_id")))
    except ValueError:
        return
    raise DocumentNotIndexedError(document_id) from exc


class HttpPersonaGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(self, request: PersonaCreateRequest) -> dict[str, Any]:
        try:
            return await self.client.post_json(
                "/personas", request.model_dump(mode="json", exclude={"document_ids"})
            )
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise PersonaGeneratorError(str(exc)) from exc


class HttpDocumentIndexer:
    """문서 전문을 LLM 서비스로 한 번만 밀어넣어 임베딩 인덱스를 만듭니다.

    이후 평가·채팅 요청에는 document_id만 오갑니다. 같은 내용을 다시 보내면
    LLM 서비스가 재계산 없이 기존 인덱스를 재사용합니다.
    """

    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def index(self, document: DocumentParseResponse) -> dict[str, Any]:
        try:
            return await self.client.post_json(
                "/documents/index",
                document.model_dump(mode="json", exclude={"saved_path"}),
            )
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise DocumentIndexError(str(exc)) from exc

    async def forget(self, document_id: UUID) -> None:
        """문서를 삭제할 때 LLM 서비스에 남은 본문·임베딩까지 지웁니다."""
        try:
            await self.client.delete(f"/documents/{document_id}/index")
        except (LlmServiceConnectionError, LlmServiceResponseError) as exc:
            raise DocumentIndexError(str(exc)) from exc


class HttpReviewGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(
        self, persona: PersonaProfile, document_id: UUID, instructions: str | None
    ) -> dict[str, Any]:
        payload = {
            "persona": persona.model_dump(mode="json"),
            "document_id": str(document_id),
            "instructions": instructions,
        }
        try:
            return await self.client.post_json("/reviews", payload)
        except LlmServiceResponseError as exc:
            _raise_if_not_indexed(exc)
            raise ReviewGeneratorError(str(exc)) from exc
        except LlmServiceConnectionError as exc:
            raise ReviewGeneratorError(str(exc)) from exc


class HttpChatGenerator:
    def __init__(self, client: HttpLlmClient) -> None:
        self.client = client

    async def generate(
        self,
        persona: PersonaProfile,
        request: ChatRequest,
        document_ids: list[UUID],
    ) -> dict[str, Any]:
        payload = {
            "persona": persona.model_dump(mode="json"),
            "message": request.message,
            # 문서 선택과 조각 검색은 LLM 서비스가 임베딩 점수로 수행합니다.
            # Backend는 소유권을 확인한 후보 목록만 넘깁니다.
            "document_ids": [str(document_id) for document_id in document_ids],
        }
        try:
            return await self.client.post_json("/chat", payload)
        except LlmServiceResponseError as exc:
            _raise_if_not_indexed(exc)
            raise ChatGeneratorError(str(exc)) from exc
        except LlmServiceConnectionError as exc:
            raise ChatGeneratorError(str(exc)) from exc
