import unittest
from uuid import uuid4
from app.models.persona import PersonaProfile, active_trait
from app.integrations.llm.contracts import PersonaGenerationRequest
from app.services.persona_service import PersonaService
from app.repositories.agent_repository import InMemoryAgentRepository


def trait(value='예산 검토', quote='예산 검토', source='description', status='supported', confidence=1, evidence_confidence=1):
    return dict(value=value, status=status, confidence=confidence,
                evidence=[dict(source_id=source, summary=quote, confidence=evidence_confidence)])


class VerificationTests(unittest.IsolatedAsyncioTestCase):
    def verify(self, item, description='예산 검토', reference=''):
        p = PersonaProfile(name='검토자', description=description, expertise=[item])
        PersonaService._verify_traits(p, PersonaGenerationRequest(name=p.name, description=description, reference_context=reference))
        return p

    def test_layout_and_fullwidth_quote(self):
        p = self.verify(trait(value='GPU 가속 검토', quote='GPU 가속 검토', source='reference_context'), reference='ＧＰＵ 가\n속 검토')
        self.assertTrue(active_trait(p.expertise[0]))

    def test_negation_is_not_removed(self):
        p = self.verify(trait(value='예산 검토를 수행한다', quote='예산 검토를 수행한다'), description='예산 검토를 수행하지 않는다')
        self.assertFalse(active_trait(p.expertise[0]))
        self.assertEqual(p.expertise[0].exclusion_reason, 'missing_quote')

    def test_tiny_quote_rejected(self):
        p = self.verify(trait(value='임의로 주장한 박사 자격', quote='예'))
        self.assertFalse(active_trait(p.expertise[0]))

    def test_short_complete_trait_supported(self):
        p = self.verify(trait(value='예산', quote='예산'))
        self.assertTrue(active_trait(p.expertise[0]))

    def test_fabricated_source_rejected(self):
        p = self.verify(trait(source='arbitrary_file'))
        self.assertFalse(active_trait(p.expertise[0]))

    def test_conflict_is_preserved_even_without_quote(self):
        p = self.verify(trait(quote='없는 인용', status='conflicting'))
        self.assertEqual(p.expertise[0].status, 'conflicting')
        self.assertFalse(active_trait(p.expertise[0]))
        self.assertTrue(any('충돌' in w for w in p.warnings))

    def test_model_unknown_not_promoted_by_matching_quote(self):
        p = self.verify(trait(status='unknown'))
        self.assertEqual(p.expertise[0].exclusion_reason, 'model_unknown')
        self.assertFalse(active_trait(p.expertise[0]))

    def test_zero_confidence_excluded(self):
        for kwargs in ({'confidence': 0}, {'evidence_confidence': 0}):
            with self.subTest(kwargs=kwargs):
                p = self.verify(trait(**kwargs))
                self.assertFalse(active_trait(p.expertise[0]))

    def test_reference_not_promoted_to_user_statement(self):
        p = self.verify(trait(source='reference_context', status='user_stated'), reference='예산 검토')
        self.assertEqual(p.expertise[0].status, 'inferred')

    async def test_unlink_invalidates_only_reference_traits(self):
        repo = InMemoryAgentRepository()
        owner, other, document = uuid4(), uuid4(), uuid4()
        p = PersonaProfile(name='검토자', document_ids=[document],
            expertise=[trait(source='reference_context')], evaluation_style=[trait(status='user_stated')])
        await repo.save(p, owner)
        await repo.unlink_document(document, other)
        self.assertTrue(active_trait((await repo.get(p.agent_id, owner)).expertise[0]))
        await repo.unlink_document(document, owner)
        updated = await repo.get(p.agent_id, owner)
        self.assertFalse(active_trait(updated.expertise[0]))
        self.assertEqual(updated.expertise[0].exclusion_reason, 'reference_changed')
        self.assertTrue(active_trait(updated.evaluation_style[0]))
        self.assertEqual(updated.document_ids, [])

    async def test_reordering_references_does_not_invalidate(self):
        repo = InMemoryAgentRepository()
        owner, d1, d2 = uuid4(), uuid4(), uuid4()
        p = PersonaProfile(name='검토자', document_ids=[d1, d2], expertise=[trait(source='reference_context')])
        await repo.save(p, owner)
        updated = await repo.set_documents(p.agent_id, owner, [d2, d1])
        self.assertTrue(active_trait(updated.expertise[0]))

    async def test_reference_replacement_invalidates(self):
        repo = InMemoryAgentRepository()
        owner = uuid4()
        p = PersonaProfile(name='검토자', document_ids=[uuid4()], expertise=[trait(source='reference_context')])
        await repo.save(p, owner)
        updated = await repo.set_documents(p.agent_id, owner, [uuid4()])
        self.assertFalse(active_trait(updated.expertise[0]))

if __name__ == '__main__':
    unittest.main()
