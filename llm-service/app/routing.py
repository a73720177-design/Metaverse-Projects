"""
채팅 요청을 문서 기반 응답과 일반 대화 응답 중 어디로 보낼지 정하는 어휘
기반 규칙.

이 판단은 HTTP 계약이 아니라 프롬프트 정책(어떤 프롬프트 템플릿을 쓸지
결정)이라서 app/prompts.py가 쓰는 별도 모듈로 둔다. main.py는 결과만
가져다 쓴다.
"""

from app.schemas_v1 import ChatGenerationRequest

_DOCUMENT_TOPIC_MARKERS = (
    "발표", "자료", "문서", "슬라이드", "첨부", "내용", "주장", "근거",
    "평가", "요약", "분석", "페이지", "개선", "질문", "document", "slide",
    "presentation", "evidence", "source", "summary",
)
_FREE_CHAT_MARKERS = (
    "안녕", "반가", "고마", "너는 누구", "넌 누구", "정체가", "날씨", "농담",
    "hello", "thank", "who are you", "weather", "tell me a joke",
)


def is_off_topic(request: ChatGenerationRequest) -> bool:
    """Classify obvious cases locally so chat latency does not double."""
    message = " ".join(request.message.lower().split())
    has_document_topic = any(marker in message for marker in _DOCUMENT_TOPIC_MARKERS)
    if request.document is not None:
        if has_document_topic:
            return False
        # Once a conversation is under way, a bare greeting/thanks marker in a
        # follow-up ("고마워, 근데 그거 무슨 뜻이야?") should not bounce it out
        # of the grounded document prompt.
        if not request.history and any(marker in message for marker in _FREE_CHAT_MARKERS):
            return True
        # With selected context, ambiguous questions should stay grounded.
        return False
    # Without a document, explicit presentation questions retain the evaluator
    # prompt while everything else uses concise free conversation.
    return not has_document_topic
