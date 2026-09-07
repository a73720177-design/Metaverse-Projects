import asyncio
import base64
import html
import re
from uuid import UUID

from app.integrations.llm.contracts import ReviewGenerator, ReviewGeneratorError
from app.models.document import DocumentParseResponse, DocumentSection
from app.models.practice import (
    ExpectedQuestion,
    ExpectedQuestionRequest,
    ExpectedQuestionResponse,
    PersonaQuestionResult,
)
from app.models.review import ReviewSource
from app.repositories.agent_repository import AgentRepository
from app.repositories.document_repository import DocumentRepository


class PracticeResourceNotFoundError(RuntimeError):
    pass


class PracticeServiceError(RuntimeError):
    pass


_QUESTION_PREFIX = re.compile(r"^(?:q(?:uestion)?|질문)\s*\d+\s*[:.)-]?\s*", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"^(?:q(?:uestion)?|질문)\s*\d*\s*[:.)-]?\s*(?:\.{3,})?$", re.IGNORECASE)


def _usable_question(value: object) -> str | None:
    raw = str(value).strip()
    if not raw or _PLACEHOLDER.fullmatch(raw):
        return None
    cleaned = _QUESTION_PREFIX.sub("", raw).strip()
    if len(cleaned) < 12 or cleaned in {"...", "…"}:
        return None
    return cleaned


def _fallback_questions(persona, documents, count: int) -> list[str]:
    filenames = ", ".join(document.filename for document in documents[:3])
    topic = filenames or "제공된 발표 자료"
    focus = persona.description.strip() or persona.role
    candidates = [
        f"{topic}에서 제시한 핵심 결론을 뒷받침하는 수치와 검증 근거를 구체적으로 설명해 주시겠습니까?",
        f"{focus} 관점에서 볼 때 이 발표안의 실행 과정에서 가장 큰 위험과 대응 방안은 무엇입니까?",
        f"{topic}의 제안이 기존 대안보다 낫다고 판단할 수 있는 비교 기준과 측정 결과는 무엇입니까?",
        f"발표에서 사용한 가정이 실제 환경에서도 유지되는지 어떤 방법으로 검증할 계획입니까?",
        f"현재 자료에서 다루지 못한 한계가 최종 결과에 미치는 영향과 보완 계획을 설명해 주시겠습니까?",
        f"예상한 성과가 나오지 않을 경우 원인을 구분하고 의사결정할 수 있는 핵심 지표는 무엇입니까?",
        f"이 발표의 주장을 재현하거나 검증하기 위해 청중에게 추가로 공개해야 할 자료는 무엇입니까?",
        f"제안한 방법을 실제 사용자에게 적용했을 때 발생할 수 있는 부작용을 어떻게 통제할 계획입니까?",
        f"발표의 결론을 바꿀 수 있는 가장 중요한 반대 근거나 실패 조건은 무엇입니까?",
        f"향후 확장 단계에서 비용과 품질 사이의 우선순위를 어떤 기준으로 결정할 계획입니까?",
    ]
    return candidates[:count]


def _avatar_data_url(name: str, role: str, gender: str, age: int | None) -> str:
    label = html.escape((name.strip() or role.strip() or "AI")[:2])
    hue = sum(ord(char) for char in f"{name}:{role}:{gender}:{age}") % 360
    hair = {
        "male": '<path d="M48 58c3-30 61-38 67 3-18-13-45-15-67-3" fill="#24202b"/>',
        "female": '<path d="M44 73c-5-48 77-57 75 2l-7 42-13-18c17-48-53-46-38 0l-13 18z" fill="#302535"/>',
        "other": '<path d="M45 65c7-35 62-39 72-3-22-8-48-7-72 3" fill="#332944"/>',
        "unspecified": '<path d="M48 60c9-27 55-31 66 0-23-9-44-9-66 0" fill="#2b2932"/>',
    }[gender]
    age_marks = "" if age is None or age < 45 else '<path d="M58 77h10M92 77h10M67 101c8 4 18 4 26 0" stroke="white" stroke-opacity=".36" stroke-width="2" fill="none"/>'
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">'
        f'<defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="hsl({hue} 72% 60%)"/>'
        f'<stop offset="1" stop-color="hsl({(hue + 55) % 360} 72% 42%)"/></linearGradient></defs>'
        '<rect width="160" height="160" rx="80" fill="url(#g)"/>'
        f'{hair}'
        '<circle cx="80" cy="61" r="29" fill="white" fill-opacity=".28"/>'
        f'{age_marks}'
        '<path d="M32 139c7-31 25-46 48-46s41 15 48 46" fill="white" fill-opacity=".23"/>'
        f'<text x="80" y="91" text-anchor="middle" font-family="sans-serif" font-size="34" '
        f'font-weight="700" fill="white">{label}</text></svg>'
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


class PracticeService:
    def __init__(
        self,
        generator: ReviewGenerator,
        agent_repository: AgentRepository,
        document_repository: DocumentRepository,
    ) -> None:
        self.generator = generator
        self.agent_repository = agent_repository
        self.document_repository = document_repository

    async def generate_expected_questions(
        self, request: ExpectedQuestionRequest, owner_id: UUID
    ) -> ExpectedQuestionResponse:
        personas = await asyncio.gather(*(
            self.agent_repository.get(persona_id, owner_id)
            for persona_id in request.persona_ids
        ))
        if any(persona is None for persona in personas):
            raise PracticeResourceNotFoundError("선택한 페르소나를 찾을 수 없습니다.")

        presentation_documents = await asyncio.gather(*(
            self.document_repository.get(document_id, owner_id)
            for document_id in request.presentation_document_ids
        ))
        if any(document is None for document in presentation_documents):
            raise PracticeResourceNotFoundError("선택한 발표 자료를 찾을 수 없습니다.")

        async def generate_for_persona(persona) -> PersonaQuestionResult:
            reference_documents = await asyncio.gather(*(
                self.document_repository.get(document_id, owner_id)
                for document_id in persona.document_ids
            ))
            valid_references = [item for item in reference_documents if item is not None]
            blocks: list[str] = []
            sections: list[DocumentSection] = []
            sources: list[ReviewSource] = []
            index = 1
            for scope, documents in (
                ("발표 자료", presentation_documents),
                ("질문자 참고자료", valid_references),
            ):
                for document in documents:
                    text = document.full_text.strip()
                    if not text:
                        continue
                    block = f"[{scope}: {document.filename}]\n{text}"
                    blocks.append(block)
                    sections.append(DocumentSection(index=index, text=block))
                    sources.append(
                        ReviewSource(
                            document_id=document.document_id,
                            filename=document.filename,
                            excerpt=text[:500],
                        )
                    )
                    index += 1
            combined = "\n\n".join(blocks)
            # The LLM service performs the final token-aware trim. This first
            # guard prevents an unbounded HTTP payload when many files exist.
            combined = combined[:80_000]
            synthetic = DocumentParseResponse(
                document_id=presentation_documents[0].document_id,
                filename="발표 프로젝트 통합 자료",
                document_type="collection",
                saved_path=presentation_documents[0].saved_path,
                sections=sections,
                full_text=combined,
            )
            instructions = (
                f"예상 질문을 {request.question_count_per_persona}개 생성하세요. "
                "발표 자료는 검토 대상이고 질문자 참고자료는 평가 관점의 근거입니다. "
                "두 종류를 혼동하지 말고 질문자가 실제로 물을 법한 질문을 작성하세요."
            )
            try:
                generated = await self.generator.generate(persona, synthetic, instructions)
            except ReviewGeneratorError as exc:
                raise PracticeServiceError("예상 질문 생성에 실패했습니다.") from exc
            unique: list[str] = []
            for question in generated.get("questions", []):
                normalized = _usable_question(question)
                if normalized and normalized not in unique:
                    unique.append(normalized)
                if len(unique) == request.question_count_per_persona:
                    break
            for question in _fallback_questions(
                persona, [*presentation_documents, *valid_references],
                request.question_count_per_persona,
            ):
                if len(unique) == request.question_count_per_persona:
                    break
                if question not in unique:
                    unique.append(question)
            return PersonaQuestionResult(
                persona_id=persona.agent_id,
                persona_name=persona.name,
                persona_role=persona.role,
                avatar_data_url=_avatar_data_url(
                    persona.name, persona.role, persona.gender, persona.age
                ),
                questions=[ExpectedQuestion(question=item, sources=sources) for item in unique],
            )

        results = await asyncio.gather(*(generate_for_persona(persona) for persona in personas))
        return ExpectedQuestionResponse(results=list(results))
