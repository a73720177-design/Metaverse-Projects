"""
Review 생성 map-reduce 파이프라인.

문서가 짧으면(REVIEW_SINGLE_PASS_CHARS 이하) app.main이 기존처럼 단일
패스로 처리한다. 문서가 길면 이 모듈이 청크로 나눠 그룹별로 claim만
추출(map)한 뒤, 모은 claims를 한 번에 정리(reduce)해서 최종 리뷰를
만든다. Ollama가 로컬 단일 인스턴스이므로 map 호출은 순차 실행한다
(병렬화하면 CPU 추론이 오히려 느려지고 OOM 위험이 있다).

LLM 호출 자체는 app.main._generate를 그대로 넘겨받아 쓴다(generate
파라미터). 그래야 기존 테스트가 monkeypatch하는 app.main.call_llm 경로가
이 모듈을 거칠 때도 그대로 유지된다.
"""

import json
import os
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.pipeline_budget import budgeted_groups, limit_groups, reduce_to_fit
from app.prompts import (
    FULL_TEXT_MAX_CHARS,
    OUTPUT_LANGUAGE_RULE,
    REVIEW_MAP_PROMPT,
    REVIEW_REDUCE_PROMPT,
    UNTRUSTED_INPUT_RULE,
    escape_prompt_data,
    render_instructions,
    render_persona,
)
from app.schemas_v1 import (
    ClaimAssessment,
    DocumentIn,
    PersonaProfileIn,
    ReviewCoverage,
    ReviewGenerationResponse,
)

_CHUNK_OVERLAP = 200


class GenerateFn(Protocol):
    def __call__(
        self, prompt: str, response_model: type[BaseModel],
        max_tokens: int | None = None, model: str | None = None,
    ) -> BaseModel: ...


class _MapResult(BaseModel):
    claims: list[ClaimAssessment] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True)
class ReviewChunk:
    section_index: int | None
    text: str


def _verify_map_claims(claims, group, filename):
    """Do not let invented map citations become evidence in the reduce step."""
    for claim in claims:
        valid = []
        for source in claim.sources:
            quote = " ".join((source.excerpt or "").split())
            if source.filename == filename and quote and any(
                (source.page is None or source.page == chunk.section_index)
                and quote in " ".join(chunk.text.split()) for chunk in group
            ):
                valid.append(source)
        claim.sources = valid
        if not valid:
            # An ungrounded model claim must not feed final prose as source data.
            continue
        yield claim


def _retain_reduce_sources(
    response: ReviewGenerationResponse, input_claims: list[dict]
) -> ReviewGenerationResponse:
    """Remove citations that were not copied exactly from verified map claims."""
    allowed = {
        (source.get("filename"), source.get("page"), source.get("excerpt"))
        for claim in input_claims
        for source in claim.get("sources", [])
        if isinstance(source, dict)
    }

    def retained(sources):
        return [
            source for source in sources
            if (source.filename, source.page, source.excerpt) in allowed
        ]

    for claim in response.claims:
        claim.sources = retained(claim.sources)
    response.feedback.positive_sources = retained(response.feedback.positive_sources)
    response.feedback.negative_sources = retained(response.feedback.negative_sources)
    return response


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"{name} 설정이 올바르지 않습니다.") from exc
    if value < 1:
        raise HTTPException(status_code=500, detail=f"{name} 설정이 올바르지 않습니다.")
    return value


def should_use_map_reduce(full_text: str) -> bool:
    threshold = _positive_env_int("REVIEW_SINGLE_PASS_CHARS", 12000)
    return len(full_text) > min(threshold, FULL_TEXT_MAX_CHARS)


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    # Small configured chunks must still advance without producing thousands
    # of almost identical windows when overlap consumes the complete chunk.
    overlap = min(max(0, overlap), chunk_size // 2)
    step = max(1, chunk_size - overlap)
    pieces: list[str] = []
    start = 0
    while start < len(text):
        pieces.append(text[start : start + chunk_size])
        if start + chunk_size >= len(text):
            break
        start += step
    return pieces


def _build_chunks(document: DocumentIn) -> list[ReviewChunk]:
    chunk_size = _positive_env_int("REVIEW_CHUNK_CHARS", 3000)
    chunks: list[ReviewChunk] = []
    if document.sections:
        for section in document.sections:
            for piece in _split_text(section.text, chunk_size, _CHUNK_OVERLAP):
                chunks.append(ReviewChunk(section_index=section.index, text=piece))
    else:
        for piece in _split_text(document.full_text, chunk_size, _CHUNK_OVERLAP):
            chunks.append(ReviewChunk(section_index=None, text=piece))
    return chunks


def _greedy_pack(chunks: list[ReviewChunk], map_chars: int) -> list[list[ReviewChunk]]:
    groups: list[list[ReviewChunk]] = []
    current: list[ReviewChunk] = []
    current_len = 0
    for chunk in chunks:
        piece_len = len(chunk.text)
        if current and current_len + piece_len > map_chars:
            groups.append(current)
            current = []
            current_len = 0
        current.append(chunk)
        current_len += piece_len
    if current:
        groups.append(current)
    return groups


def _evenly_sample(items: list[list[ReviewChunk]], k: int) -> list[list[ReviewChunk]]:
    """Pick k items spread across the list so start/middle/end all survive."""
    n = len(items)
    if k >= n:
        return items
    if k <= 1:
        return [items[n // 2]]
    used: set[int] = set()
    sampled = []
    for i in range(k):
        idx = round(i * (n - 1) / (k - 1))
        while idx in used and idx < n - 1:
            idx += 1
        used.add(idx)
        sampled.append(items[idx])
    return sampled


def _pack_chunks(
    chunks: list[ReviewChunk],
) -> tuple[list[list[ReviewChunk]], bool]:
    map_chars = _positive_env_int("REVIEW_MAP_CHARS", 12000)
    max_calls = _positive_env_int("REVIEW_MAX_MAP_CALLS", 6)
    groups = _greedy_pack(chunks, map_chars)
    if len(groups) <= max_calls:
        return groups, False
    return _evenly_sample(groups, max_calls), True


def _render_group(group: list[ReviewChunk]) -> str:
    parts = []
    for chunk in group:
        label = f"[구간 {chunk.section_index}]" if chunk.section_index is not None else "[구간]"
        parts.append(f"{label}\n{chunk.text}")
    return "\n\n".join(parts)


def _persona_json(persona: PersonaProfileIn) -> str:
    return render_persona(persona)


def generate_review_map_reduce(
    *,
    persona: PersonaProfileIn,
    document: DocumentIn,
    instructions: str | None,
    generate: GenerateFn,
    model: str | None,
) -> ReviewGenerationResponse:
    chunks = _build_chunks(document)

    persona_json = _persona_json(persona)
    instructions_text = render_instructions(instructions)

    def map_prompt(group):
        return REVIEW_MAP_PROMPT.format(
            persona_json=persona_json,
            filename=escape_prompt_data(document.filename),
            instructions=instructions_text,
            chunk_text=escape_prompt_data(_render_group(group)),
        )

    all_groups = budgeted_groups(chunks, map_prompt, 768, _positive_env_int("REVIEW_MAP_CHARS", 12000))
    groups = limit_groups(all_groups, "REVIEW", _evenly_sample)
    truncated = len(groups) < len(all_groups)
    all_claims: list[dict] = []
    for group in groups:
        result = generate(map_prompt(group), _MapResult, max_tokens=768, model=model)
        all_claims.extend(claim.model_dump(mode="json") for claim in
                          _verify_map_claims(result.claims, group, document.filename))

    def final_prompt(claims):
        prompt = REVIEW_REDUCE_PROMPT.format(
            persona_json=persona_json,
            filename=escape_prompt_data(document.filename),
            instructions=instructions_text,
            claims_json=escape_prompt_data(json.dumps(claims, ensure_ascii=False)),
        )
        if truncated:
            prompt += "\n일부 구간만 표본 검토했습니다. 피드백에 이 한계를 밝히고 문서 전체를 검토했다고 표현하지 마세요.\n"
        return prompt

    def compact_prompt(claims):
        return (
            "중간 검토 결과를 압축하세요. 핵심 주장, 상충 근거, verdict와 출처 페이지를 유지하고 "
            "중복만 합치세요. 인용문과 주장은 짧게, claims는 최대 3개로 작성하세요. "
            "시각 분석의 불확실성을 유지하세요.\n"
            + UNTRUSTED_INPUT_RULE + "\n" + OUTPUT_LANGUAGE_RULE
            + "\n<document_data>\n"
            + escape_prompt_data(json.dumps(claims, ensure_ascii=False))
            + "\n</document_data>"
        )

    # Preserve the pre-reduction allow-list. Intermediate compaction is another
    # model call and therefore cannot be trusted to define new citations.
    verified_source_claims = list(all_claims)
    all_claims = reduce_to_fit(
        all_claims, final_prompt=final_prompt, final_tokens=2048,
        compact_prompt=compact_prompt, response_model=_MapResult, field="claims",
        generate=generate, model=model, compact_tokens=768,
    )
    response = generate(final_prompt(all_claims), ReviewGenerationResponse, max_tokens=2048, model=model)
    response = _retain_reduce_sources(response, verified_source_claims)

    coverage = ReviewCoverage(
        total_chunks=sum(len(group) for group in all_groups),
        analyzed_chunks=sum(len(group) for group in groups),
        truncated=truncated,
        selection_method="even_sample" if truncated else "full",
    )
    return response.model_copy(update={"coverage": coverage})
