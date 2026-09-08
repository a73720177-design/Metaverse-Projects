import asyncio
import logging

from app.integrations.llm.contracts import EmbeddingGenerator, EmbeddingGeneratorError
from app.models.document import DocumentParseResponse, EmbeddedChunk
from app.repositories.document_repository import DocumentRepository
from app.services.chunking import split_document

logger = logging.getLogger(__name__)


class EmbeddingIndexer:
    """Chunks a saved document, embeds it in batches, and stores the vectors.

    Runs as a fire-and-forget background task from the upload endpoint: a
    slow or unavailable embedding model must never block or fail the upload
    response, so failures are only logged.
    """

    def __init__(
        self,
        generator: EmbeddingGenerator,
        repository: DocumentRepository,
        *,
        model: str,
        chunk_size: int = 700,
        overlap: int = 100,
        batch_size: int = 32,
    ) -> None:
        self.generator = generator
        self.repository = repository
        self.model = model
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.batch_size = batch_size

    async def index_document(self, document: DocumentParseResponse) -> None:
        chunks = split_document(document, chunk_size=self.chunk_size, overlap=self.overlap)
        if not chunks:
            return
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), self.batch_size):
            batch = chunks[start : start + self.batch_size]
            vectors.extend(await self.generator.embed([chunk.text for chunk in batch]))
        rows = [
            EmbeddedChunk(
                chunk_index=chunk.chunk_index,
                section_index=chunk.section_index,
                content=chunk.text,
                embedding=vector,
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        await self.repository.save_embeddings(document.document_id, self.model, rows)

    def schedule(self, document: DocumentParseResponse) -> "asyncio.Task[None]":
        async def _run() -> None:
            try:
                await self.index_document(document)
            except EmbeddingGeneratorError:
                logger.exception("문서 %s 임베딩 인덱싱 실패", document.document_id)

        task = asyncio.create_task(_run())
        task.add_done_callback(_log_unexpected_failure)
        return task


def _log_unexpected_failure(task: "asyncio.Task[None]") -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("문서 임베딩 인덱싱 태스크가 예기치 않게 실패했습니다.", exc_info=exc)
