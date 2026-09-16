"""Budget-aware map packing and hierarchical reduction without silent sampling."""
import json
import os
from dataclasses import replace

from fastapi import HTTPException

from app.context_budget import positive_int, prompt_fits, require_prompt_fits


def analysis_mode(prefix: str) -> str:
    mode = os.getenv(f"{prefix}_ANALYSIS_MODE", "fast").strip().lower()
    if mode not in {"fast", "full"}:
        raise HTTPException(status_code=500, detail=f"{prefix}_ANALYSIS_MODE는 fast 또는 full이어야 합니다.")
    return mode


def budgeted_groups(chunks, render_prompt, output_tokens: int, max_chars: int):
    """Split oversized chunks, keeping original source indices and every character."""
    require_prompt_fits(render_prompt([]), output_tokens)
    fitted = []
    pending = list(reversed(chunks))
    while pending:
        chunk = pending.pop()
        if prompt_fits(render_prompt([chunk]), output_tokens):
            fitted.append(chunk)
        elif len(chunk.text) > 1:
            middle = len(chunk.text) // 2
            pending.extend([replace(chunk, text=chunk.text[middle:]), replace(chunk, text=chunk.text[:middle])])
        else:
            require_prompt_fits(render_prompt([chunk]), output_tokens)
    groups, current = [], []
    for chunk in fitted:
        candidate = current + [chunk]
        if current and (sum(len(c.text) for c in candidate) > max_chars
                        or not prompt_fits(render_prompt(candidate), output_tokens)):
            groups.append(current)
            current = []
        current.append(chunk)
    if current:
        groups.append(current)
    return groups


def limit_groups(groups, prefix: str, sample):
    if analysis_mode(prefix) == "full":
        # Explicitly reject excessive work; never call a sampled result "full".
        if len(groups) > positive_int(f"{prefix}_FULL_MAX_MAP_CALLS", 512):
            raise HTTPException(status_code=422, detail="전체 분석 호출 한도를 초과했습니다. 파일을 나누거나 분석 한도를 조정해 주세요.")
        return groups
    return sample(groups, positive_int(f"{prefix}_MAX_MAP_CALLS", 6))


def reduce_to_fit(items, *, final_prompt, final_tokens, compact_prompt,
                  response_model, field, generate, model, compact_tokens=512):
    """Feed every mapped item through bounded intermediate reductions as needed."""
    require_prompt_fits(final_prompt([]), final_tokens)
    for _ in range(12):
        if prompt_fits(final_prompt(items), final_tokens):
            return items
        batches, current = [], []
        for item in items:
            if current and not prompt_fits(compact_prompt(current + [item]), compact_tokens):
                batches.append(current)
                current = []
            require_prompt_fits(compact_prompt([item]), compact_tokens)
            current.append(item)
        if current:
            batches.append(current)
        reduced = []
        for batch in batches:
            result = generate(compact_prompt(batch), response_model,
                              max_tokens=compact_tokens, model=model)
            reduced.extend(value.model_dump(mode="json") for value in getattr(result, field))
        # Do not discard items or spin forever if the model fails to compress.
        if (not reduced and items) or len(json.dumps(reduced, ensure_ascii=False)) >= len(json.dumps(items, ensure_ascii=False)):
            raise HTTPException(status_code=502, detail="중간 분석 결과를 문맥 한도에 맞게 압축하지 못했습니다.")
        items = reduced
    raise HTTPException(status_code=502, detail="단계별 분석 압축 횟수 한도를 초과했습니다.")
