import os
import unittest
from uuid import uuid4
from unittest.mock import patch
from app.main import generate_expected_questions, generate_persona, _LANGUAGE_RETRY_RULE, _call_llm_as_json
from app.schemas_v1 import ExpectedQuestionGenerationRequest, ExpectedQuestionGenerationResponse, PersonaGenerationRequest, PersonaGenerationResponse
from app.context_budget import prompt_fits


class ContextRegression(unittest.TestCase):
    def test_truncated_json_is_retried_once(self):
        with patch('app.main.call_llm', side_effect=['{"questions":[', '{"questions":[]}']) as run:
            self.assertEqual(_call_llm_as_json('질문 생성', {'type': 'object', 'required': ['questions']}, max_tokens=768), {'questions': []})
            self.assertEqual(run.call_count, 2)

    def test_persona_long_reference_also_reserves_retry_budget(self):
        request = PersonaGenerationRequest(name='시설운영 책임자', description='시설운영 책임자', reference_context='예산과 운영 기준을 검토한다. ' * 150)
        def generated(prompt, schema, *, max_tokens, model):
            self.assertTrue(prompt_fits(prompt + _LANGUAGE_RETRY_RULE, max_tokens))
            return PersonaGenerationResponse(role='시설운영 책임자')
        with patch.dict(os.environ, {"LLM_PROVIDER": "vllm", "LLM_MAX_MODEL_LEN": "4096"}), patch('app.main._generate', side_effect=generated):
            generate_persona(request)

    def test_retry_with_large_exclusion_list_fits_4k(self):
        request = ExpectedQuestionGenerationRequest(
            persona={"agent_id": str(uuid4()), "name": "운영 검토자", "description": "시설운영 책임자"},
            question_count=9,
            evidence=[{"id": "e1", "scope": "presentation", "text": "운영 예산 1800만원, 기간 8주, 혼합배출률 목표 18%. " * 80}],
            excluded_questions=["운영 예산 근거와 인력 배치 방법을 구체적으로 설명할 수 있나요?" * 8] * 40,
        )
        def generated(prompt, schema, *, max_tokens, model):
            self.assertTrue(prompt_fits(prompt, max_tokens))
            self.assertIn('1800', prompt)
            return ExpectedQuestionGenerationResponse(questions=[])
        with patch.dict(os.environ, {"LLM_PROVIDER": "vllm", "LLM_MAX_MODEL_LEN": "4096"}), patch('app.main._generate', side_effect=generated) as run:
            generate_expected_questions(request)
            self.assertEqual(run.call_count, 1)
            self.assertLessEqual(run.call_args.kwargs['max_tokens'], 1280)

    def test_reference_only_never_generates_presentation_claim(self):
        request = ExpectedQuestionGenerationRequest(persona={"agent_id": str(uuid4()), "name": "평가자"}, evidence=[{"id": "r1", "scope": "persona_reference", "text": "운영 지침"}])
        with patch('app.main._generate') as run:
            self.assertEqual(generate_expected_questions(request).questions, [])
            run.assert_not_called()

if __name__ == '__main__':
    unittest.main()
