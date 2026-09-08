from pathlib import Path
from uuid import UUID

import pytest

from app.integrations.llm.contracts import EmbeddingGeneratorError
from app.models.document import DocumentParseResponse, DocumentSection
from app.repositories.document_repository import InMemoryDocumentRepository
from app.services.embedding_service import EmbeddingIndexer
from app.services.rag_service import DocumentContextSelector, HybridContextSelector


DOCUMENT_ID = UUID("33333333-3333-3333-3333-333333333333")

# 두 청크는 임베딩 공간에서 직교하도록 설계했다: 질의와 청크2가 같은 방향(코사인
# 유사도 1.0)이고 청크1은 90도(유사도 0.0)라, 순수 lexical 점수(청크1이 1, 청크2가
# 0)와는 반대되는 순위를 만들어낸다.
QUERY = "매출 현황을 알려줘"
DECOY_TEXT = "매출 문의는 다른 페이지를 참고하세요"  # lexical만 보면 1순위(오탐)
SYNONYM_TEXT = "수익이 지난 분기 대비 25퍼센트 증가했습니다"  # 실제로 관련 있는 내용


def _document() -> DocumentParseResponse:
    sections = [
        DocumentSection(index=1, text=DECOY_TEXT),
        DocumentSection(index=2, text=SYNONYM_TEXT),
    ]
    return DocumentParseResponse(
        document_id=DOCUMENT_ID,
        filename="report.pdf",
        document_type="pdf",
        saved_path=Path("report.pdf"),
        sections=sections,
        full_text="\n".join(section.text for section in sections),
    )


class FakeEmbeddingGenerator:
    """질의·청크 텍스트를 미리 정한 벡터에 매핑하는 결정론적 가짜 임베더."""

    _VECTORS = {
        QUERY: [1.0, 0.0],
        SYNONYM_TEXT: [1.0, 0.0],
        DECOY_TEXT: [0.0, 1.0],
    }

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._VECTORS[text] for text in texts]


class FailingEmbeddingGenerator:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingGeneratorError("임베딩 서버에 연결할 수 없습니다.")


def _selector(generator, repository) -> HybridContextSelector:
    return HybridContextSelector(
        embedding_generator=generator,
        document_repository=repository,
        chunk_size=200,
        overlap=20,
        max_chunks=1,
        candidate_multiplier=1,
    )


@pytest.mark.asyncio
async def test_hybrid_selects_synonym_only_chunk_over_lexical_decoy() -> None:
    repository = InMemoryDocumentRepository()
    document = _document()
    indexer = EmbeddingIndexer(
        FakeEmbeddingGenerator(), repository, model="fake-model", chunk_size=200, overlap=20
    )
    await indexer.index_document(document)

    selector = _selector(FakeEmbeddingGenerator(), repository)
    selected = await selector.select(document, QUERY)

    assert len(selected.sections) == 1
    assert selected.sections[0].index == 2
    assert "수익" in selected.full_text


@pytest.mark.asyncio
async def test_hybrid_falls_back_to_lexical_when_not_indexed() -> None:
    repository = InMemoryDocumentRepository()
    document = _document()
    selector = _selector(FakeEmbeddingGenerator(), repository)
    lexical = DocumentContextSelector(chunk_size=200, overlap=20, max_chunks=1)

    hybrid_result = await selector.select(document, QUERY)
    lexical_result = await lexical.select(document, QUERY)

    assert hybrid_result.full_text == lexical_result.full_text


@pytest.mark.asyncio
async def test_hybrid_falls_back_to_lexical_when_embedding_call_fails() -> None:
    repository = InMemoryDocumentRepository()
    document = _document()
    await EmbeddingIndexer(
        FakeEmbeddingGenerator(), repository, model="fake-model", chunk_size=200, overlap=20
    ).index_document(document)

    selector = _selector(FailingEmbeddingGenerator(), repository)
    lexical = DocumentContextSelector(chunk_size=200, overlap=20, max_chunks=1)

    hybrid_result = await selector.select(document, QUERY)
    lexical_result = await lexical.select(document, QUERY)

    assert hybrid_result.full_text == lexical_result.full_text


@pytest.mark.asyncio
async def test_save_and_search_chunks_round_trip_through_in_memory_repository() -> None:
    repository = InMemoryDocumentRepository()
    document = _document()
    await EmbeddingIndexer(
        FakeEmbeddingGenerator(), repository, model="fake-model", chunk_size=200, overlap=20
    ).index_document(document)

    assert await repository.has_embeddings(document.document_id) is True

    results = await repository.search_chunks(document.document_id, [1.0, 0.0], limit=2)
    assert results[0].content == SYNONYM_TEXT
    assert results[0].score == pytest.approx(1.0)
    assert results[-1].content == DECOY_TEXT
    assert results[-1].score == pytest.approx(0.0)

    other_document_id = UUID("44444444-4444-4444-4444-444444444444")
    assert await repository.has_embeddings(other_document_id) is False
    assert await repository.search_chunks(other_document_id, [1.0, 0.0], limit=2) == []
