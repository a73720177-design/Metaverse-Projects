"""Run in the LLM image with the candidate app on PYTHONPATH."""
import os
import unittest
from unittest.mock import Mock, patch
from app import llm_client as client


class HealthTests(unittest.TestCase):
    def response(self, value):
        return Mock(ok=True, json=Mock(return_value=value))

    def test_wrong_ollama_tag_is_unhealthy(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}), patch.multiple(
            client, OLLAMA_CHAT_MODEL="qwen3:4b", OLLAMA_REVIEW_MODEL="qwen3:4b",
            OLLAMA_QUESTION_MODEL="qwen3:4b", OLLAMA_SUMMARY_MODEL="qwen3:4b"
        ), patch.object(client.requests, "get", return_value=self.response(
            {"models": [{"name": "qwen3:8b"}, {"name": "bge-m3:latest"}]})):
            self.assertFalse(client.check_ollama_health())

    def test_ollama_latest_alias(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}), patch.multiple(
            client, OLLAMA_CHAT_MODEL="qwen3:4b", OLLAMA_REVIEW_MODEL="qwen3:4b",
            OLLAMA_QUESTION_MODEL="qwen3:4b", OLLAMA_SUMMARY_MODEL="qwen3:4b"
        ), patch.object(client.requests, "get", return_value=self.response(
            {"models": [{"name": "qwen3:4b"}, {"name": "bge-m3:latest"}]})):
            self.assertTrue(client.check_ollama_health())

    def test_vllm_requires_embedding_model(self):
        for models, expected in [([], False), ([{"name": "bge-m3:latest"}], True)]:
            with self.subTest(models=models), patch.dict(os.environ, {"LLM_PROVIDER": "vllm", "VLLM_MODEL": "served"}), patch.object(
                client.requests, "get", side_effect=[self.response({"data": [{"id": "served"}]}), self.response({"models": models})]):
                self.assertEqual(client.check_ollama_health(), expected)

    def test_vllm_wrong_alias(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "vllm", "VLLM_MODEL": "served"}), patch.object(
            client.requests, "get", return_value=self.response({"data": [{"id": "other"}]})):
            self.assertFalse(client.check_ollama_health())

    def test_malformed_server_response(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "vllm"}), patch.object(client.requests, "get", return_value=self.response(None)):
            self.assertFalse(client.check_ollama_health())


if __name__ == "__main__":
    unittest.main()
