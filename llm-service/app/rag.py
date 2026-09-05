"""
bge-m3 임베딩 기반 검색 레이어.

모든 답변 경로(최초 평가, 채팅 피드백)는 생성 전에 이 모듈로 관련 자료
조각을 찾는다. 경로마다 다른 것은 "검색 여부"가 아니라 "검색 후 추론
(think) 여부"다.

문서 전문은 Backend가 업로드 시점에 한 번만 밀어넣고(POST /documents/index),
그 이후 요청에는 document_id만 오간다. 그래서 채팅 한 번에 수십만 자를
HTTP로 실어 나르지 않아도 되고, 임베딩도 문서당 한 번만 계산한다.

임베딩 벡터는 프로세스 메모리(LRU)와 로컬 디스크에 함께 보관한다. DB나
pgvector에는 저장하지 않는다. 디스크 캐시가 지워지거나 문서를 인덱싱하기
전에 요청이 오면 DocumentNotIndexedError를 던지고, Backend가 문서를 다시
밀어넣은 뒤 재시도한다.
"""

import json
import hashlib
import logging
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import numpy as np
from dotenv import load_dotenv

from app.llm_client import LLMError, embed_texts

load_dotenv()

logger = logging.getLogger(__name__)

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
# 최초 평가는 문서를 넓게 봐야 하므로 채팅보다 많은 조각을 가져온다.
RAG_REVIEW_TOP_K = int(os.getenv("RAG_REVIEW_TOP_K", "12"))
RAG_SIMILARITY_THRESHOLD = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.45"))
RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "700"))
RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "100"))
RAG_CACHE_DIR = Path(os.getenv("RAG_CACHE_DIR", ".rag_cache"))
RAG_CACHE_DOCS = int(os.getenv("RAG_CACHE_DOCS", "32"))

# 검색 질의가 통째로 공백이거나 기호뿐이면 임베딩할 의미가 없다.
_MEANINGFUL_RE = re.compile(r"[0-9A-Za-z가-힣]")


class RagError(Exception):
    """임베딩·검색 실패."""


class DocumentNotIndexedError(RagError):
    """요청한 문서가 아직 인덱싱되지 않음. Backend가 다시 밀어넣어야 한다."""

    def __init__(self, document_id: UUID) -> None:
        super().__init__(f"document not indexed: {document_id}")
        self.document_id = document_id


@dataclass(frozen=True)
class Chunk:
    document_id: UUID
    filename: str
    document_type: str
    index: int  # 원본 섹션(PDF 페이지 / PPT 슬라이드) 번호
    text: str


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class SearchResult:
    chunks: list[ScoredChunk]

    @property
    def top_score(self) -> float:
        return self.chunks[0].score if self.chunks else 0.0

    def is_relevant(self, threshold: float | None = None) -> bool:
        limit = RAG_SIMILARITY_THRESHOLD if threshold is None else threshold
        return self.top_score >= limit

    def as_context(self) -> str:
        """검색된 조각을 프롬프트에 넣을 텍스트 블록으로 만든다."""
        if not self.chunks:
            return "(검색된 자료 없음)"
        return "\n\n".join(
            f"[출처: {item.chunk.filename} 구간 {item.chunk.index}]\n{item.chunk.text}"
            for item in self.chunks
        )


@dataclass
class _IndexedDocument:
    document_id: UUID
    filename: str
    document_type: str
    fingerprint: str
    chunks: list[Chunk]
    matrix: np.ndarray  # (n, d), L2 정규화된 float32


def _fingerprint(full_text: str) -> str:
    return hashlib.sha256(full_text.encode("utf-8")).hexdigest()


def _normalize(matrix: np.ndarray) -> np.ndarray:
    """코사인 유사도를 내적 한 번으로 끝내기 위해 행을 미리 정규화한다."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


def split_text(text: str, section_index: int) -> list[tuple[int, str]]:
    """한 섹션을 겹침을 둔 고정 길이 조각으로 자른다."""
    stripped = text.strip()
    if not stripped:
        return []
    pieces: list[tuple[int, str]] = []
    start = 0
    step = max(RAG_CHUNK_SIZE - RAG_CHUNK_OVERLAP, 1)
    while start < len(stripped):
        end = min(start + RAG_CHUNK_SIZE, len(stripped))
        pieces.append((section_index, stripped[start:end]))
        if end == len(stripped):
            break
        start += step
    return pieces


class DocumentIndexStore:
    """문서별 청크와 임베딩을 들고 있는 저장소."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_documents: int | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir is not None else RAG_CACHE_DIR
        self.max_documents = max_documents or RAG_CACHE_DOCS
        self._memory: OrderedDict[UUID, _IndexedDocument] = OrderedDict()

    # --- 인덱싱 -------------------------------------------------------

    def index(
        self,
        document_id: UUID,
        filename: str,
        document_type: str,
        sections: list[tuple[int, str]],
        full_text: str,
    ) -> tuple[int, bool]:
        """문서를 청킹·임베딩해 보관한다.

        Returns:
            (조각 개수, 기존 인덱스를 재사용했는지)
        """
        fingerprint = _fingerprint(full_text)
        existing = self._load(document_id)
        if existing is not None and existing.fingerprint == fingerprint:
            return len(existing.chunks), True

        raw_chunks: list[tuple[int, str]] = []
        source = sections or [(1, full_text)]
        for index, text in source:
            raw_chunks.extend(split_text(text, index))
        if not raw_chunks:
            raise RagError("문서에서 인덱싱할 텍스트를 찾지 못했습니다.")

        try:
            vectors = embed_texts([text for _, text in raw_chunks])
        except LLMError as exc:
            raise RagError(str(exc)) from exc

        indexed = _IndexedDocument(
            document_id=document_id,
            filename=filename,
            document_type=document_type,
            fingerprint=fingerprint,
            chunks=[
                Chunk(
                    document_id=document_id,
                    filename=filename,
                    document_type=document_type,
                    index=index,
                    text=text,
                )
                for index, text in raw_chunks
            ],
            matrix=_normalize(np.asarray(vectors, dtype=np.float32)),
        )
        self._remember(indexed)
        self._save_to_disk(indexed)
        return len(indexed.chunks), False

    def forget(self, document_id: UUID) -> None:
        self._memory.pop(document_id, None)
        self._cache_path(document_id).unlink(missing_ok=True)

    # --- 검색 ---------------------------------------------------------

    def search(
        self, document_ids: list[UUID], query: str, top_k: int | None = None
    ) -> SearchResult:
        """지정한 문서들에서 질의와 가장 가까운 조각을 찾는다.

        Raises:
            DocumentNotIndexedError: 인덱스가 없는 document_id가 있을 때
            RagError: 임베딩 호출 실패
        """
        if not document_ids or not _MEANINGFUL_RE.search(query):
            return SearchResult(chunks=[])

        documents = [self._require(document_id) for document_id in document_ids]
        try:
            query_vector = embed_texts([query])[0]
        except LLMError as exc:
            raise RagError(str(exc)) from exc
        query_array = _normalize(np.asarray([query_vector], dtype=np.float32))[0]

        scored: list[ScoredChunk] = []
        for document in documents:
            scores = document.matrix @ query_array
            scored.extend(
                ScoredChunk(chunk=chunk, score=float(score))
                for chunk, score in zip(document.chunks, scores)
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return SearchResult(chunks=scored[: top_k or RAG_TOP_K])

    def is_indexed(self, document_id: UUID) -> bool:
        return self._load(document_id) is not None

    def describe(self, document_id: UUID) -> tuple[str, str]:
        """인덱싱된 문서의 (파일명, 문서 종류). 요청에 문서 메타가 없어도 된다.

        Raises:
            DocumentNotIndexedError: 인덱스가 없을 때
        """
        document = self._require(document_id)
        return document.filename, document.document_type

    # --- 내부 -------------------------------------------------------

    def _require(self, document_id: UUID) -> _IndexedDocument:
        document = self._load(document_id)
        if document is None:
            raise DocumentNotIndexedError(document_id)
        return document

    def _remember(self, document: _IndexedDocument) -> None:
        self._memory[document.document_id] = document
        self._memory.move_to_end(document.document_id)
        while len(self._memory) > self.max_documents:
            self._memory.popitem(last=False)

    def _cache_path(self, document_id: UUID) -> Path:
        return self.cache_dir / f"{document_id}.npz"

    def _save_to_disk(self, document: _IndexedDocument) -> None:
        """프로세스를 재시작해도 임베딩을 다시 계산하지 않도록 저장한다."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            meta = {
                "document_id": str(document.document_id),
                "filename": document.filename,
                "document_type": document.document_type,
                "fingerprint": document.fingerprint,
                "chunks": [
                    {"index": chunk.index, "text": chunk.text}
                    for chunk in document.chunks
                ],
            }
            np.savez_compressed(
                self._cache_path(document.document_id),
                embeddings=document.matrix,
                meta=np.array(json.dumps(meta, ensure_ascii=False)),
            )
        except OSError:
            # 캐시는 성능 최적화일 뿐이라 실패해도 인덱싱 자체는 성공으로 둔다.
            logger.warning("RAG 디스크 캐시 저장 실패 (document_id=%s)", document.document_id)

    def _load(self, document_id: UUID) -> _IndexedDocument | None:
        cached = self._memory.get(document_id)
        if cached is not None:
            self._memory.move_to_end(document_id)
            return cached

        path = self._cache_path(document_id)
        if not path.exists():
            return None
        try:
            with np.load(path, allow_pickle=False) as payload:
                meta = json.loads(str(payload["meta"]))
                matrix = np.asarray(payload["embeddings"], dtype=np.float32)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            logger.warning("RAG 디스크 캐시를 읽지 못해 무시합니다 (document_id=%s)", document_id)
            return None

        chunks = [
            Chunk(
                document_id=document_id,
                filename=meta["filename"],
                document_type=meta["document_type"],
                index=int(item["index"]),
                text=item["text"],
            )
            for item in meta["chunks"]
        ]
        if len(chunks) != matrix.shape[0]:
            logger.warning("RAG 캐시의 조각 수와 벡터 수가 다릅니다 (document_id=%s)", document_id)
            return None

        document = _IndexedDocument(
            document_id=document_id,
            filename=meta["filename"],
            document_type=meta["document_type"],
            fingerprint=meta["fingerprint"],
            chunks=chunks,
            matrix=matrix,
        )
        self._remember(document)
        return document


store = DocumentIndexStore()
