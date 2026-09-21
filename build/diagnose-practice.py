import asyncio
import json
import os
import httpx
from sqlalchemy import select
from app.db.database import get_session_factory
from app.db.tables import PracticeSessionTable
from app.dependencies import get_practice_service, get_persona_service
from app.models.practice import ExpectedQuestionRequest
from app.models.persona import PersonaCreateRequest
from app.repositories.practice_repository import InMemoryPracticeRepository

async def main():
    async with get_session_factory()() as db:
        row = await db.scalar(select(PracticeSessionTable).order_by(PracticeSessionTable.created_at.desc()).limit(1))
        request = ExpectedQuestionRequest.model_validate(row.payload['request'])
        owner = row.owner_id
    service = get_practice_service()
    service.session_repository = InMemoryPracticeRepository()
    persona_service = get_persona_service()
    selected = []
    for pid in request.persona_ids:
        persona = await service.agent_repository.get(pid, owner)
        documents = await persona_service._owned_documents(persona.document_ids, owner)
        generation = persona_service._generation_request(PersonaCreateRequest(name=persona.name, description=persona.description, document_ids=persona.document_ids), documents)
        print(json.dumps({'name': persona.name, 'reference_chars': len(generation.reference_context), 'description': persona.description, 'trait_count': len(persona.expertise)+len(persona.evaluation_style)}, ensure_ascii=False), flush=True)
        if '김민정' in persona.name:
            selected.append(pid)
    if not selected:
        raise RuntimeError('Target persona not found')
    request = request.model_copy(update={'persona_ids': selected})
    original = httpx.AsyncClient.request
    async def inspected(client, method, url, **kwargs):
        response = await original(client, method, url, **kwargs)
        if '/practice/questions' in str(url):
            payload = kwargs.get('json') or {}
            print(json.dumps({'status': response.status_code, 'count': payload.get('question_count'), 'excluded_chars': sum(len(x) for x in payload.get('excluded_questions', [])), 'error': response.json() if response.status_code >= 400 else None}, ensure_ascii=False), flush=True)
        return response
    httpx.AsyncClient.request = inspected
    result = await service.generate_expected_questions(request, owner)
    print(json.dumps([{'name': r.persona_name, 'count': r.generated_count, 'warnings': r.warnings} for r in result.results], ensure_ascii=False), flush=True)

asyncio.run(main())
