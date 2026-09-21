import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from io import BytesIO
import sys
sys.dont_write_bytecode = True

path = Path(__file__).parent / 'payload/llm-service/app/installer_check.py'
spec = importlib.util.spec_from_file_location('installer_check', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(module.os.environ, {"LLM_PROVIDER": "ollama", "OLLAMA_CHAT_MODEL": "qwen3:4b"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_vllm_probes_actual_provider_and_ollama_embedding(self):
        results = [BytesIO(b'{"choices":[{"message":{"content":"OK"}}]}'),
                   BytesIO(b'{"embeddings":[[0.1,0.2]]}')]
        with patch.dict(module.os.environ, {"LLM_PROVIDER": "vllm", "VLLM_MODEL": "demo-model", "VLLM_BASE_URL": "http://vllm:8000"}), patch.object(module.urllib.request, 'urlopen', side_effect=results) as post:
            module.main()
            self.assertEqual(post.call_args_list[0].args[0].full_url, 'http://vllm:8000/v1/chat/completions')
            self.assertEqual(module.json.loads(post.call_args_list[0].args[0].data)['model'], 'demo-model')
            self.assertTrue(post.call_args_list[1].args[0].full_url.endswith('/api/embed'))

    def test_vllm_failure_is_not_hidden_by_ollama(self):
        with patch.dict(module.os.environ, {"LLM_PROVIDER": "vllm", "VLLM_MODEL": "demo-model"}), patch.object(module.urllib.request, 'urlopen', return_value=BytesIO(b'{"choices":[]}')):
            with self.assertRaisesRegex(RuntimeError, 'empty'):
                module.main()

    def test_generation_and_embedding(self):
        results = [BytesIO(b'{"response":"OK"}'), BytesIO(b'{"embeddings":[[0.1,0.2]]}')]
        with patch.object(module.urllib.request, 'urlopen', side_effect=results) as post:
            module.main()
            self.assertEqual(post.call_count, 2)
            self.assertEqual(module.json.loads(post.call_args.args[0].data)['keep_alive'], 0)

    def test_ollama_memory_error(self):
        result = module.urllib.error.HTTPError('http://ollama', 500, 'error', {}, BytesIO(b'model requires more system memory'))
        with patch.object(module.urllib.request, 'urlopen', side_effect=result):
            with self.assertRaisesRegex(RuntimeError, 'memory'):
                module.main()

    def test_timeout_is_not_restart(self):
        with patch.object(module.urllib.request, 'urlopen', side_effect=TimeoutError):
            with self.assertRaisesRegex(RuntimeError, 'Windows restart is not required'):
                module.main()

    def test_empty_output_is_failure(self):
        with patch.object(module.urllib.request, 'urlopen', return_value=BytesIO(b'{"response":""}')):
            with self.assertRaisesRegex(RuntimeError, 'empty'):
                module.main()


if __name__ == '__main__':
    unittest.main()
