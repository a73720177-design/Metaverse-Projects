"""Optional local reranking. Indices refer only to the supplied, authorized texts."""
import math
import os
from urllib.parse import urlsplit

import httpx

from app.config import _get_positive_int


def reranking_enabled() -> bool:
    mode = os.getenv("RAG_RERANK_MODE", "off").strip().lower()
    if mode not in {"off", "local"}:
        raise ValueError("RAG_RERANK_MODE must be off or local")
    return mode == "local"


class RerankerClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.url = os.getenv("RAG_RERANK_URL", "http://127.0.0.1:8003").rstrip("/")
        target = urlsplit(self.url)
        if (target.scheme != "http" or target.hostname not in {"localhost", "127.0.0.1", "::1"}
                or target.username or target.password or target.path not in {"", "/"}
                or target.query or target.fragment):
            raise ValueError("RAG_RERANK_URL must be a loopback HTTP URL")
        self.timeout = _get_positive_int("RAG_RERANK_TIMEOUT_SECONDS", 10)
        self.transport = transport

    async def rank(self, query: str, documents: list[str]) -> list[int]:
        if not documents:
            return []
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport,
                                     trust_env=False, follow_redirects=False) as client:
            response = await client.post(self.url + "/rerank", json={
                "query": query, "documents": documents,
            })
            response.raise_for_status()
        results = response.json()["results"]
        if not isinstance(results, list) or len(results) != len(documents):
            raise ValueError("Incomplete reranking response")
        seen = set()
        for result in results:
            index, score = result["index"], result["relevance_score"]
            if (type(index) is not int or not 0 <= index < len(documents) or index in seen
                    or type(score) not in {int, float} or not math.isfinite(score)
                    or not 0 <= score <= 1):
                raise ValueError("Invalid reranking score/index")
            seen.add(index)
        return [row["index"] for row in sorted(results, key=lambda row: (-row["relevance_score"], row["index"]))]
