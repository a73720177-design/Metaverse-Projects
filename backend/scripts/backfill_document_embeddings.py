"""Explicit, resumable backfill: python -m scripts.backfill_document_embeddings."""
import asyncio

from sqlalchemy import text
from app.db.database import close_db, get_session_factory
from app.services.vector_rag import VectorRag


async def main():
    failed = 0
    try:
        async with get_session_factory()() as session:
            documents = (await session.execute(text(
                "SELECT document_id, owner_id FROM documents WHERE owner_id IS NOT NULL ORDER BY document_id"
            ))).all()
        service = VectorRag()
        for document_id, owner_id in documents:
            try:
                count = await service.index_document(document_id, owner_id)
                print(f"{document_id}: {count} chunks indexed", flush=True)
            except Exception as exc:
                failed += 1
                print(f"{document_id}: FAILED ({type(exc).__name__}); rerun to retry", flush=True)
    finally:
        await close_db()
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
