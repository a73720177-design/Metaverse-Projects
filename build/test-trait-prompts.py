import unittest
from uuid import uuid4
from app.schemas_v1 import PersonaProfileIn
from app.prompts import render_persona


class PromptExclusionTests(unittest.TestCase):
    def test_excluded_values_never_reach_prompt(self):
        variants = [('unknown', 1, True), ('conflicting', 1, True), ('supported', 0, True), ('inferred', 1, False)]
        for status, confidence, evidence in variants:
            with self.subTest(status=status, confidence=confidence, evidence=evidence):
                item = dict(value='EXCLUDED_TRAIT_SENTINEL', status=status, confidence=confidence,
                    evidence=[dict(source_id='description', summary='검토 관점', confidence=1)] if evidence else [])
                persona = PersonaProfileIn(agent_id=uuid4(), name='검토자', expertise=[item], evaluation_style=[item])
                self.assertNotIn('EXCLUDED_TRAIT_SENTINEL', render_persona(persona))

    def test_valid_inference_is_labelled(self):
        persona = PersonaProfileIn(agent_id=uuid4(), name='검토자', expertise=[dict(value='예산 검토', status='inferred', confidence=.6, evidence=[dict(source_id='reference_context', summary='예산 검토', confidence=1)])])
        self.assertIn('예산 검토 (추론된 관점)', render_persona(persona))

if __name__ == '__main__':
    unittest.main()
