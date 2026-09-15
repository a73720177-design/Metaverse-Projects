"""
요약 생성 map-reduce 파이프라인.

문서가 짧으면(SUMMARY_SINGLE_PASS_CHARS 이하) app.main이 기존처럼 단일
패스로 처리한다. 문서가 길면 이 모듈이 청크로 나눠 그룹별로 핵심 요점만
추출(map)한 뒤, 모은 요점을 한 번에 정리(reduce)해서 최종 요약을 만든다.
구조는 review_pipeline.py의 map-reduce와 동일하지만, 요약 전용 환경변수
(SUMMARY_*)와 스타일(brief/detailed/outline) 처리를 쓴다.

Ollama가 로컬 단일 인스턴스이므로 map 호출은 순차 실행한다(병렬화하면
CPU 추론이 오히려 느려지고 OOM 위험이 있다).

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

from app.prompts import SUMMARY_MAP_PROMPT, SUMMARY_REDUCE_PROMPT
from app.schemas_v1 import DocumentIn, PersonaProfileIn, SummaryGenerationResponse, SummaryStyle

_CHUNK_OVERLAP = 200

_STYLE_GUIDANCE: dict[SummaryStyle, str] = {
    SummaryStyle.BRIEF: "전체 내용을 3~5문장으로 간결하게 요약하세요.",
    SummaryStyle.DETAILED: "문단 흐름에 따라 자세히 요약하고, 마지막에 전체 결론을 덧붙이세요.",
    SummaryStyle.OUTLINE: "summary는 핵심 흐름을 담은 3~5문장으로 짧게 쓰고, 세부 구조는 outline으로 표현하세요.",
}

_STYLE_MAX_TOKENS: dict[SummaryStyle, int] = {
    SummaryStyle.BRIEF: 512,
    SummaryStyle.DETAILED: 1024,
    SummaryStyle.OUTLINE: 768,
}


class GenerateFn(Protocol):
    def __call__(
        self, prompt: str, response_model: type[BaseModel],
        max_tokens: int | None = None, model: str | None = None,
    ) -> BaseModel: ...


class _MapPoint(BaseModel):
    point: str
    source_index: int | None = None


class _MapResult(BaseModel):
    points: list[_MapPoint] = Field(default_factory=list, max_length=5)


@dataclass(frozen=True)
class SummaryChunk:
    section_index: int | None
    text: str


def style_max_tokens(style: SummaryStyle) -> int:
    return _STYLE_MAX_TOKENS[style]


def style_guidance(style: SummaryStyle) -> str:
    return _STYLE_GUIDANCE[style]


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"{name} 설정이 올바르지 않습니다.") from exc
    if value < 1:
        raise HTTPException(status_code=500, detail=f"{name} 설정이 올바르지 않습니다.")
    return value


def should_use_map_reduce(full_text: str) -> bool:
    threshold = _positive_env_int("SUMMARY_SINGLE_PASS_CHARS", 12000)
    return len(full_text) > threshold


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
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


def _build_chunks(document: DocumentIn) -> list[SummaryChunk]:
    chunk_size = _positive_env_int("SUMMARY_CHUNK_CHARS", 3000)
    chunks: list[SummaryChunk] = []
    if document.sections:
        for section in document.sections:
            for piece in _split_text(section.text, chunk_size, _CHUNK_OVERLAP):
                chunks.append(SummaryChunk(section_index=section.index, text=piece))
    else:
        for piece in _split_text(document.full_text, chunk_size, _CHUNK_OVERLAP):
            chunks.append(SummaryChunk(section_index=None, text=piece))
    return chunks


def _greedy_pack(chunks: list[SummaryChunk], map_chars: int) -> list[list[SummaryChunk]]:
    groups: list[list[SummaryChunk]] = []
    current: list[SummaryChunk] = []
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


def _evenly_sample(items: list[list[SummaryChunk]], k: int) -> list[list[SummaryChunk]]:
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


def _pack_chunks(chunks: list[SummaryChunk]) -> list[list[SummaryChunk]]:
    map_chars = _positive_env_int("SUMMARY_MAP_CHARS", 12000)
    max_calls = _positive_env_int("SUMMARY_MAX_MAP_CALLS", 6)
    groups = _greedy_pack(chunks, map_chars)
    if len(groups) <= max_calls:
        return groups
    return _evenly_sample(groups, max_calls)


def _render_group(group: list[SummaryChunk]) -> str:
    parts = []
    for chunk in group:
        label = f"[구간 {chunk.section_index}]" if chunk.section_index is not None else "[구간]"
        parts.append(f"{label}\n{chunk.text}")
    return "\n\n".join(parts)


def persona_block(persona: PersonaProfileIn | None) -> str:
    if persona is None:
        return "(특정 평가자 관점 없이 일반적인 독자 관점으로 요약합니다.)"
    return json.dumps(persona.model_dump(mode="json"), ensure_ascii=False)


def generate_summary_map_reduce(
    *,
    document: DocumentIn,
    style: SummaryStyle,
    persona: PersonaProfileIn | None,
    generate: GenerateFn,
    model: str | None,
) -> SummaryGenerationResponse:
    chunks = _build_chunks(document)
    groups = _pack_chunks(chunks)
    block = persona_block(persona)

    all_points: list[dict] = []
    for group in groups:
        prompt = SUMMARY_MAP_PROMPT.format(
            persona_block=block,
            filename=document.filename,
            chunk_text=_render_group(group),
        )
        result = generate(prompt, _MapResult, max_tokens=512, model=model)
        all_points.extend(point.model_dump(mode="json") for point in result.points)

    reduce_prompt = SUMMARY_REDUCE_PROMPT.format(
        persona_block=block,
        filename=document.filename,
        style_guidance=_STYLE_GUIDANCE[style],
        points_json=json.dumps(all_points, ensure_ascii=False),
    )
    return generate(
        reduce_prompt, SummaryGenerationResponse,
        max_tokens=style_max_tokens(style), model=model,
    )
