"""Offline microbenchmark; does not measure database, embeddings or LLM latency."""

from pathlib import Path
from statistics import median
import json
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.document import DocumentParseResponse, DocumentSection
from app.services.rag_service import DocumentContextSelector


def main():
    sections = [DocumentSection(
        index=index + 1,
        text=f"사업 계획 {index} 매출 성장률 고객 수와 기술 개발 일정 검토. " * 40,
    ) for index in range(120)]
    document = DocumentParseResponse(
        filename="benchmark.pdf", document_type="pdf", saved_path=Path("benchmark.pdf"),
        sections=sections, full_text="\n".join(section.text for section in sections),
    )
    selector = DocumentContextSelector()
    expected = selector.select(document, "매출 성장률")
    timings = {}
    for mode in ("recompute_features", "cached_features"):
        elapsed = []
        for _ in range(21):
            if mode == "recompute_features":
                selector._term_cache.clear()
            started = perf_counter()
            actual = selector.select(document, "매출 성장률")
            elapsed.append((perf_counter() - started) * 1000)
            assert actual == expected, "Caching changed the retrieved evidence"
        timings[mode] = round(median(elapsed), 2)
    print(json.dumps({
        "pages": len(sections), "characters": len(document.full_text),
        "median_ms": timings,
        "scope": "Warm chunk cache; feature recomputation versus cached feature statistics only",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
