# 기획안: llm-service `prompts.py` RAG 정합화

- 상태: 초안 (구현 착수 전)
- 대상 브랜치: `claude/llm-service-prompts-rag-3a9103`
- 주 수정 파일: `llm-service/app/prompts.py`
- 종속 수정: `llm-service/app/main.py`, `backend/app/services/rag_service.py`, 양쪽 테스트

---

## 1. 배경

RAG 검색은 전부 Backend에 있고, llm-service는 그 결과를 "문서"로 받는다.

```
ChatService._resolve_context()
  └ RAG_MODE=lexical → DocumentContextSelector.select()   (BM25)
  └ RAG_MODE=vector  → VectorRag.select_context()          (pgvector)
        └ 두 경로 모두 combine_document_contexts()로 수렴
              └ full_text = "[파일: {filename} / 구간 {index}]\n{본문}" 블록의 연결
                    └ HttpChatGenerator.generate()가 sections를 제외하고 full_text만 전송
                          └ prompts.build_chat_prompt() → render_document(with_index=False)
                                → full_text를 "[참고 문서]"로 통째 덤프
```

즉 **프롬프트에 들어오는 것은 문서가 아니라 검색된 청크 묶음인데, 프롬프트는 그 사실을 모른다.**
`prompts.py`는 이것을 문서 전체인 것처럼 제시하고 있어 근거 기반 응답 품질이 검색기 성능만큼 나오지 않는다.

## 2. 목표 / 비목표

**목표**

1. 채팅 프롬프트가 입력을 "검색된 일부 근거"로 정확히 표현한다.
2. Backend가 만든 청크 라벨과 프롬프트가 기대하는 라벨을 하나의 계약으로 고정한다.
3. 근거 부족/부분 근거 상황에 대한 모델 행동 지침을 프롬프트에 명시한다.
4. 컨텍스트 절삭이 청크 경계를 깨지 않는다.
5. `sources`가 "검색된 전부"가 아니라 "답변이 실제 사용한 근거"만 담는다.

**비목표**

- 검색 알고리즘(BM25/pgvector) 자체 변경
- 리뷰/요약 파이프라인의 map-reduce 구조 변경 (이 경로는 전체 문서를 받으므로 RAG가 아님)
- `/chat/stream`의 SSE 응답 형식 변경
- **채팅 경로에 구조화 출력(JSON schema) 도입** — `llm-service/app/main.py:293-295`에 남은
  의도적 결정(CPU Ollama에서 JSON 생성이 한 줄 답변에도 출력 예산을 소진)을 되돌리지 않는다

## 3. 현황 진단

| # | 문제 | 근거 위치 |
|---|---|---|
| 1 | `[참고 문서]` + `파일명: 통합 참고 자료`로 제시되어 모델이 문서 전체를 받았다고 착각. "자료에 없음" 판단을 못 함 | `llm-service/app/prompts.py:427` |
| 2 | 본문 라벨은 `[파일: X / 구간 N]`인데 프롬프트는 이 라벨을 설명하지 않음. 리뷰 경로는 `[구간 N]`을 쓰고 설명함 → **라벨 방언 2종** | `backend/app/services/rag_service.py:48` vs `llm-service/app/prompts.py:161` |
| 3 | 부분 근거/빈약한 근거에 대한 지침 없음. Backend는 검색 0건일 때만 차단(`_NO_GROUNDED_CONTEXT_TYPE`), `GROUNDING_MODE` 기본값은 `off` | `backend/app/services/chat_service.py:136`, `backend/app/config.py:186` |
| 4 | `sources`를 Backend가 **검색된 청크 전부**로 기계 생성. 답변이 실제 사용한 청크와 무관. 반면 프롬프트는 모델의 출처 표기를 금지. UI의 SOURCE MAP이 검색만 되고 안 쓰인 문서에도 "채팅 사용" 배지를 켠다 | `backend/app/integrations/llm/generators.py:80`, `backend/app/services/chat_service.py:183`, `src/App.jsx:423` |
| 5 | `FULL_TEXT_MAX_CHARS=24_000` vs RAG 예산 `RAG_MAX_CONTEXT_CHARS=4000` → `truncate()`가 사실상 no-op. 실제 절삭은 생문자 슬라이스라 마지막 청크가 라벨만 남거나 문장 중간에서 끊김 | `llm-service/app/prompts.py:55`, `llm-service/app/main.py:222` |

## 4. 결정 필요 사항

### D-1. 인용 방식 — **확정: A안(인라인 마커) + 마커 파싱 기반 `sources` 필터**

검토했던 두 안:

- **A안(채택):** 본문에 `[근거 N]` 인라인 표기. 생성은 기존과 같은 순수 텍스트.
- **B안(기각):** `ChatGenerationResponse`에 `used_chunks: list[int]` 추가 → 구조화 출력으로 사용 청크 회수.

B안을 기각한 이유:

1. **UI는 스트리밍 경로만 쓴다.** `src/App.jsx:270`이 `streamChat`만 호출하고(`src/api.js:106` →
   `llm-service/app/main.py:307`), 비스트리밍 `/chat`은 UI에서 쓰이지 않는다. 구조화 출력은
   토큰 증분 표시와 양립하지 않으므로 B안은 실사용 경로에 적용할 수 없다.
2. **채팅의 JSON 생성 회피는 의도된 결정이다.** `llm-service/app/main.py:293-295` 주석 참조.
   B안은 이 결정을 되돌린다.
3. **충실도는 인라인 인용이 유리하다.** `[근거 N]`은 문장을 쓰는 시점에 귀속을 강제하는 반면,
   `used_chunks`는 사후 자기보고라 작은 모델이 "준 근거 전부"를 나열하는 쪽으로 무너지기 쉽다.
4. **B안의 실익은 A안으로 얻을 수 있다.** 스트리밍 경로는
   `backend/app/services/chat_service.py:299-317`에서 토큰을 모두 모아 `answer`를 완성한 뒤에야
   `sources`를 붙인다. 그 지점에서 완성된 답변의 마커를 파싱하면 구조화 출력 없이 사용 청크만
   남길 수 있다. → **Phase 8**

### D-2. 근거 부족 시 강도

- 권장: 프롬프트 레벨에서는 **부분 답변 + 결핍 명시**(거부가 아님). 완전 차단은 기존 `GROUNDING_MODE=strict` 경로에 맡긴다.

---

## 5. 변경 설계

### Phase 1 — 청크 라벨 계약 통일 (선행 필수)

`prompts.py`를 라벨 형식의 단일 정의처로 삼고 Backend를 맞춘다.

```python
# llm-service/app/prompts.py
CHUNK_LABEL_TEMPLATE = "[근거 {ordinal}] 파일: {filename} / 구간 {index}"
CHUNK_LABEL_RE = re.compile(r"^\[근거 (\d+)\] 파일: (.+?) / 구간 (\d+)\]?$", re.MULTILINE)
```

- `ordinal`(1..N) 신설. 모델이 인용할 짧은 키가 필요하고, `구간 N`은 문서마다 중복되어 다중 문서에서 인용 키로 쓸 수 없다.
- `backend/app/services/rag_service.py:48`의 `f"[파일: {filename} / 구간 {index}]\n"`를 동일 형식으로 교체.
- 두 서비스가 분리되어 import 공유가 불가하므로 형식 문자열을 양쪽에 두고, **계약 테스트로 drift를 막는다**.

**완료 기준:** Backend가 생성한 `full_text`가 `CHUNK_LABEL_RE`에 전부 매칭된다.

### Phase 2 — 검색 컨텍스트 전용 렌더러

`render_document()`는 리뷰/요약(전체 문서)용으로 유지하고, 채팅용을 분리 신설한다.

```python
_CONTEXT_START = "=== 검색된 근거 시작 ==="
_CONTEXT_END   = "=== 검색된 근거 끝 ==="
RAG_CONTEXT_MAX_CHARS = 4_000   # backend RAG_MAX_CONTEXT_CHARS와 일치시킨다

def render_retrieved_context(document: DocumentIn | None) -> str:
    """검색기가 고른 청크 묶음을 '문서 전체가 아님'을 명시해 감싼다."""
```

동작:
- 문서 없음 → `"(검색된 근거 없음)"`
- 헤더 문장: *"아래는 사용자 질문과 관련해 검색된 일부 구간이며, 문서 전체가 아닙니다."*
- `sections`가 전달되면 직접 라벨링, 없으면 Backend가 붙인 라벨을 그대로 통과
- 절삭은 **청크 경계에서만** (반쪽 라벨 방지)

### Phase 3 — RAG 정책 상수 신설

채팅 경로에서 기존 `NO_HALLUCINATION_RULE`(과도하게 일반적)을 아래로 대체한다.

```python
GROUNDING_RULE = (
    "답변은 위 [검색된 근거] 안의 내용만 사실 근거로 사용하세요. "
    "근거에 없는 내용을 덧붙여야 한다면 '자료에서 확인되지 않음'이라고 먼저 밝히세요."
)
PARTIAL_CONTEXT_RULE = (
    "검색된 근거가 질문에 부분적으로만 답한다면, 확인 가능한 부분만 답하고 "
    "무엇이 자료에 없는지 한 문장으로 알려주세요."
)
CITATION_RULE = (
    "근거를 사용한 문장 끝에 [근거 N] 표기를 붙이세요. 근거 목록이나 JSON은 만들지 마세요."
)
```

### Phase 4 — `CHAT_PROMPT` 재작성

구조를 `페르소나 → 검색 근거 → 근거 사용 규칙 → 대화 이력 → 질문` 순으로 재배열한다.

- 섹션 헤더 `[참고 문서]` → `[검색된 근거]`
- 기존 "출처 목록이나 JSON을 직접 만들지 말고…" 문장을 `CITATION_RULE`로 교체
- `UNTRUSTED_INPUT_RULE`의 구분자 언급이 `=== 검색된 근거 ===`까지 포함하도록 수정
- `FREE_CHAT_PROMPT`는 **변경하지 않는다** (근거 없는 일반 대화 경로)
- `routing.is_off_topic()`은 유지하되, 문서가 있는데 근거가 비는 경우 free-chat으로 빠지지 않는지 재확인

⚠️ 헤더 문자열 변경은 아래 테스트를 깨뜨린다. 같은 커밋에서 수정할 것:
`llm-service/tests/test_prompts.py:321`, `llm-service/tests/test_main.py:240,259,392,417`

### Phase 5 — 토큰 예산을 청크 단위로

`llm-service/app/main.py:222` `_fit_chat_context()`의 `full_text[:max_document_chars]` 슬라이스를
`prompts.trim_context_to_chunks(full_text, max_chars)` 호출로 교체한다.

- 라벨 단위로 **뒤에서부터 청크를 통째로** 버린다 (검색 랭킹상 뒤쪽이 덜 중요).
- 청크 하나도 못 넣는 경우는 기존과 동일하게 422를 유지한다.

### Phase 6 — 리뷰/요약 정리 (최소 변경)

- `REVIEW_*` / `SUMMARY_*`의 `[구간 N]` 지침은 **유지**한다 (map-reduce가 이 라벨을 파싱).
- Phase 1의 렌더링 헬퍼를 쓰도록 호출부만 통일.
- `PROMPT_VERSION`을 구현일 날짜로 갱신 (`llm-service/app/prompts.py:33`).

### Phase 7 — 테스트

`llm-service/tests/test_prompts.py` 신규:

1. `render_retrieved_context()`가 "문서 전체가 아닙니다" 문장을 포함한다
2. 문서가 `None`이면 `(검색된 근거 없음)`이고 근거 규칙이 프롬프트에 들어가지 않는다
3. 청크 경계 절삭이 반쪽 라벨을 만들지 않는다
4. `CHAT_PROMPT`에 `GROUNDING_RULE`/`CITATION_RULE`이 포함되고 `FREE_CHAT_PROMPT`에는 포함되지 않는다
5. Backend 라벨 형식을 하드코딩한 회귀 테스트(계약 고정)

`backend/tests/test_llm_v1_contract.py` 신규:

6. `combine_document_contexts()` 산출 `full_text`가 `CHUNK_LABEL_RE` 형식과 일치한다

기존 수정: `test_prompts.py:317-325`, `test_main.py:240/259/392/417`

### Phase 8 — `sources`를 실제 사용 근거로 필터 (마커 파싱, 필수)

A안의 `[근거 N]` 마커를 Backend가 파싱해 `sources`를 좁힌다. LLM 계약(스키마·SSE 형식) 변경 없음.

대상:
- `backend/app/services/chat_service.py:183` `_sources()` — 완성된 `answer`를 인자로 받아
  마커에 등장한 ordinal의 section만 반환
- `backend/app/services/chat_service.py:299-317` `open_stream()` — 토큰 조립 완료 후 호출부 수정
- `backend/app/integrations/llm/generators.py:80` — 비스트리밍 경로도 같은 규칙으로 통일

함께 처리해야 하는 3가지 (누락 시 A안이 오히려 품질을 떨어뜨린다):

1. **grounding 보정.** 인라인 마커의 "근거" 토큰은 청크 본문에 없어
   `backend/app/services/grounding_service.py`의 lexical containment를 떨어뜨린다.
   `_apply_grounding()`에는 **마커를 제거한 사본**을 넘기고, 저장·표시용 `answer`에는 마커를 남긴다.
2. **ordinal ↔ sources 인덱스 정렬.** 마커가 클릭 가능하려면 `[근거 N]`의 N이 `sources[N-1]`과
   맞아야 한다. Phase 1의 ordinal 부여 순서를 Backend가 `document.sections`를 순회하는 순서와
   동일하게 고정한다.
3. **범위 밖 마커 방어.** 청크가 3개인데 `[근거 7]`을 지어내는 경우가 있다. 파싱 시 범위를 벗어난
   마커는 본문에서 제거하고 `sources`에도 반영하지 않는다.

**완료 기준:** 검색은 되었으나 답변이 인용하지 않은 문서에 `src/App.jsx:423`의 "채팅 사용" 배지가
켜지지 않는다.

---

## 6. 작업 순서 체크리스트

- [x] D-1 확정 — A안(인라인 마커) + Phase 8 마커 파싱
- [ ] Phase 1: 라벨 계약 통일 + 양쪽 계약 테스트 (ordinal 순서를 `document.sections` 순회 순서와 일치)
- [ ] Phase 2: `render_retrieved_context()` 추가
- [ ] Phase 3: RAG 정책 상수 추가
- [ ] Phase 4: `CHAT_PROMPT` 재작성 + 깨진 테스트 수정
- [ ] Phase 5: `_fit_chat_context()` 청크 단위 절삭
- [ ] Phase 6: 리뷰/요약 호출부 통일, `PROMPT_VERSION` 갱신
- [ ] Phase 7: 테스트 추가 및 `pytest` 전체 통과
- [ ] Phase 8: 마커 파싱 `sources` 필터 + grounding 보정 + 범위 밖 마커 방어

## 7. 리스크

| 리스크 | 완화 |
|---|---|
| Backend/llm-service 라벨 형식 drift | 양쪽 계약 테스트(Phase 7-5, 7-6)로 고정 |
| 프롬프트 문구 변경에 따른 응답 품질 회귀 | `PROMPT_VERSION` 갱신 후 `llm-service/scripts/benchmark_chat.py`로 전후 비교 |
| 헤더 문자열 변경이 다수 테스트를 깨뜨림 | 변경과 테스트 수정을 같은 커밋으로 묶음 |
| `render_document()`와 신규 렌더러의 역할 혼동 | `render_document`=전체 문서(리뷰/요약), `render_retrieved_context`=검색 결과(채팅)로 docstring에 명시 |
| 인라인 마커가 grounding 점수를 낮춰 오탐 증가 | Phase 8-1: 채점용 사본에서만 마커 제거 |
| 모델이 마커를 아예 안 붙이면 `sources`가 빈 배열이 됨 | Phase 8: 마커가 0개면 기존 동작(검색 청크 전부)으로 폴백하고 로그를 남긴다 |
| 모델이 존재하지 않는 ordinal을 생성 | Phase 8-3: 범위 밖 마커 제거 |

## 8. 별건: 인접 영역에서 발견한 죽은 코드

`backend/app/services/chat_service.py:138-165`에서 `sections`/`blocks`를 약 30줄에 걸쳐 조립해
`document`(161행)에 대입한 직후, 166행 `combine_document_contexts(...)`가 그 값을 즉시 덮어쓴다.

- 완전한 죽은 코드이며, 매 채팅 요청마다 무의미한 문자열 조립 비용이 발생한다.
- 본 기획안의 작업 영역과 겹치므로 Phase 1과 함께 정리하는 것을 권장한다. (범위 밖으로 둘 경우 별도 이슈)
