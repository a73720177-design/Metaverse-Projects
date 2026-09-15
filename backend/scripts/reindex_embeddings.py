"""Repair missing or stale embeddings for one owner's persisted documents."""

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app import config  # noqa: E402,F401 - load backend/.env
from app.db.database import get_session_factory  # noqa: E402
from app.db.tables import DocumentTable  # noqa: E402
from app.services.vector_rag import VectorRag  # noqa: E402


async def reindex(owner_id: UUID) -> int:
    async with get_session_factory()() as session:
        document_ids = list((await session.scalars(
            select(DocumentTable.document_id)
            .where(DocumentTable.owner_id == owner_id)
            .order_by(DocumentTable.created_at)
        )).all())
    total = 0
    rag = VectorRag()
    for document_id in document_ids:
        updated = await rag.index_document(document_id, owner_id)
        total += updated
        print(f"{document_id}: {updated} chunks indexed", flush=True)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-id", type=UUID, required=True)
    args = parser.parse_args()
    total = asyncio.run(reindex(args.owner_id))
    print(f"Completed: {total} chunks indexed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
