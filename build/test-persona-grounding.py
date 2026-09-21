import unittest
from uuid import uuid4
from unittest.mock import AsyncMock
from app.models.persona import PersonaProfile, PersonaCreateRequest
from app.integrations.llm.contracts import PersonaGenerationRequest
from app.services.persona_service import PersonaService


class PersonaRegression(unittest.IsolatedAsyncioTestCase):
    def test_empty_model_traits_keep_explicit_user_viewpoint(self):
        persona = PersonaProfile(name='운영 평가자', description='시설 운영과 예산 검토')
        request = PersonaGenerationRequest(name=persona.name, description=persona.description)
        PersonaService._verify_traits(persona, request)
        self.assertEqual(persona.expertise, [])
        self.assertEqual(persona.evaluation_style[0].status, 'user_stated')
        self.assertEqual(persona.evaluation_style[0].evidence[0].summary, persona.description)
        self.assertEqual(persona.warnings, [])

    def test_fabricated_expertise_is_not_validated(self):
        persona = PersonaProfile(name='검토자', expertise=[{'value': '박사 자격', 'status': 'supported', 'confidence': 1, 'evidence': [{'source_id': 'description', 'summary': '존재하지 않는 자격', 'confidence': 1}]}])
        PersonaService._verify_traits(persona, PersonaGenerationRequest(name='검토자', description='예산 검토'))
        self.assertEqual(persona.expertise[0].status, 'unknown')
        self.assertEqual(persona.expertise[0].evidence, [])

    async def test_document_connection_recomputes_persona(self):
        pid, owner, docid = uuid4(), uuid4(), uuid4()
        current = PersonaProfile(agent_id=pid, name='검토자', description='예산 검토')
        repository = AsyncMock()
        repository.get.return_value = current
        documents = AsyncMock()
        documents.get.return_value = object()
        service = PersonaService(AsyncMock(), repository, documents)
        service.update = AsyncMock(return_value=current)
        await service.update_documents(pid, [docid], owner)
        service.update.assert_awaited_once()
        self.assertEqual(service.update.call_args.args[1].document_ids, [docid])
        repository.set_documents.assert_not_called()

if __name__ == '__main__':
    unittest.main()
