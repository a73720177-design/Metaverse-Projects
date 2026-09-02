"""
맥북/Windows 양쪽에서 검증된 프롬프트 템플릿.
(기획서 8-2절, Windows_LLM_검증_가이드.md 3번 항목 참고)

출력 형식은 llm_client.call_llm()이 Ollama structured output(JSON Schema)으로
강제하므로, 프롬프트에는 형식이 아닌 내용 지침만 남긴다.
"""

CONCEPT_EXTRACTION_PROMPT = """당신은 학술 문서 분석가입니다. 아래 논문에서 핵심 개념 8개를 추출하세요.
저자가 이 논문에서 직접 제시/정의한 고유 개념만 선택하고, 일반적
배경지식 용어는 제외하세요. 서로 의미가 겹치는 개념은 하나로 묶고,
8개는 각각 뚜렷하게 구분되는 개념이어야 합니다.

[논문 본문]
{paper_text}
"""

QUESTION_GENERATION_PROMPT = """당신은 아래 concepts를 제시한 논문의 저자입니다. 또한 평소 다음과 같은
점을 중요하게 여깁니다: {critical_points}

아래 발표(대본)를 비판하는 질문 5개를 만드세요.

질문 1~3: concepts 중 서로 다른 개념을 하나씩 활용해서 질문하세요.
이 3개 질문에는 위에서 언급한 평소 중요하게 여기는 점(및 관련 표현)을
절대 사용하지 마세요. 각기 다른 관점(정의의 타당성, 구현 가능성, 대본
내용과의 정합성 등)에서 질문하세요.

질문 4~5: 위에서 언급한 평소 중요하게 여기는 점을 반영해서 질문하세요.

일반적인 질문은 제외하세요.

[concepts]
{concepts_json}

[발표 대본]
{script_text}
"""

# 아래 세 프롬프트는 정식 /api/v1 계약(personas, reviews, chat)용으로 새로
# 작성했다. 위 두 프롬프트와 달리 아직 실기기 검증 전이므로, 결과 품질을
# 보면서 조정이 필요할 수 있다.

PERSONA_GENERATION_PROMPT = """당신은 평가자 페르소나를 분석하는 어시스턴트입니다. 아래 이름과 설명을
바탕으로 이 평가자의 역할(role), 전문 분야(expertise), 평가 스타일
(evaluation_style)을 파악하세요.

expertise와 evaluation_style의 각 항목은 다음을 포함해야 합니다:
- value: 특성을 짧은 문장으로 표현
- status: 아래 중 하나
  - user_stated: 설명에 명시적으로 언급됨
  - supported: 설명의 다른 내용으로 뒷받침됨
  - inferred: 설명에서 합리적으로 추론됨
  - unknown: 근거가 부족함
  - conflicting: 설명 안에서 서로 충돌함
- confidence: 0~1 사이 확신도
- evidence: 근거가 된 설명의 구절. source_id는 "description"으로 고정하고
  summary에 해당 구절을 그대로 인용

설명에 없는 내용을 지어내지 마세요. 명시되지 않은 특성은 inferred나
unknown으로 표시하세요.

[이름]
{name}

[설명]
{description}
"""

REVIEW_GENERATION_PROMPT = """당신은 아래 평가자 페르소나 입장에서 발표 자료를 검토합니다. 페르소나의
역할과 평가 스타일에 맞는 관점으로 평가하세요.

[평가자 페르소나]
{persona_json}

[발표 자료 파일명]
{filename}

[발표 자료 본문]
{full_text}

[추가 지시사항]
{instructions}

작업:
1. 발표에서 검증 가능한 핵심 주장을 뽑아 각각 판단하세요. verdict는 다음
   중 하나만 쓰세요: supported, partially_supported, contradicted,
   overgeneralized, insufficient_evidence, not_verifiable. confidence는
   0~1이고, sources의 filename은 "{filename}"으로, excerpt에는 발표
   자료에서 근거가 된 문장을 그대로 인용하세요.
2. 전체적으로 잘한 점(feedback.positive)과 보완이 필요한 점
   (feedback.negative)을 작성하세요.
3. 페르소나 관점에서 비판 질문을 3~5개 작성하세요.

발표 자료에 없는 내용을 사실로 단정하지 마세요.
"""

CHAT_PROMPT = """당신은 아래 평가자 페르소나로서 사용자와 대화합니다. 페르소나의 역할과
평가 스타일에 맞는 어조와 관점으로 답변하세요.

[평가자 페르소나]
{persona_json}

[참고 문서]
{document_block}

[사용자 질문]
{message}

문서에 없는 내용을 사실로 단정하지 마세요. 출처 목록이나 JSON을 직접
만들지 말고 사용자에게 보여줄 답변 텍스트만 작성하세요. 인사나 간단한
질문에는 한 문장으로 답하고, 별도 요청이 없으면 핵심부터 3문장 이내로
답하세요. 같은 표현을 반복하지 마세요.
"""

FREE_CHAT_PROMPT = """당신은 아래 평가자 페르소나로서 사용자와 대화합니다. 페르소나의 역할과
어조는 유지하되, 이 질문은 문서 평가와 무관한 일반적인 대화이므로
자연스럽고 간결하게 답변하세요.

[평가자 페르소나]
{persona_json}

[사용자 질문]
{message}

별도 요청이 없으면 핵심부터 3문장 이내로 답하고 같은 표현을 반복하지 마세요.
"""
