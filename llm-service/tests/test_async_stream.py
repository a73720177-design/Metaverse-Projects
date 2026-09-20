import asyncio
import httpx
import pytest
from app import llm_client
from app.main import stream_chat
from app.schemas_v1 import ChatGenerationRequest


@pytest.mark.parametrize('provider', ['ollama', 'vllm'])
def test_provider_stream_cancel_closes_socket_and_releases_slot(monkeypatch, provider):
    monkeypatch.setenv('LLM_PROVIDER', provider)
    monkeypatch.setenv('VLLM_MODEL', 'test-model')
    async def run():
        closed = asyncio.Event()
        waiting = asyncio.Event()
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield (b'{"response":"first","done":false}\n' if provider == 'ollama' else
                       b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n')
                waiting.set()
                await asyncio.Event().wait()
            async def aclose(self):
                closed.set()
        async def handler(request):
            return httpx.Response(200, stream=Body())
        real_client = httpx.AsyncClient
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
        stream = llm_client.stream_llm_async('hello')
        assert await asyncio.wait_for(anext(stream), .5) == 'first'
        pending = asyncio.create_task(anext(stream))
        await asyncio.wait_for(waiting.wait(), .5)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert closed.is_set()
        assert llm_client._GENERATION_SLOTS.acquire(blocking=False)
        llm_client._GENERATION_SLOTS.release()
    asyncio.run(run())


def test_endpoint_filters_reasoning_before_validated_output(monkeypatch):
    async def run():
        closed = asyncio.Event()
        async def provider(*args, **kwargs):
            try:
                for text in ['<thi', 'nk>private', '</think>첫 응답']:
                    yield text
            finally:
                closed.set()
        monkeypatch.setattr('app.main.stream_llm', provider)
        response = await stream_chat(ChatGenerationRequest(persona={'name': '평가자', 'agent_id': '11111111-1111-1111-1111-111111111111'}, message='안녕'))
        iterator = response.body_iterator
        first = await asyncio.wait_for(anext(iterator), .5)
        assert '첫 응답' in first and 'private' not in first and 'done' not in first
        await iterator.aclose()
        assert closed.is_set()
    asyncio.run(run())


@pytest.mark.parametrize('provider', ['ollama', 'vllm'])
def test_async_sampling_matches_sync_configuration(monkeypatch, provider):
    import json
    monkeypatch.setenv('LLM_PROVIDER', provider)
    monkeypatch.setenv('VLLM_MODEL', 'served-model')
    captured = {}
    async def run():
        async def handler(request):
            captured.update(json.loads(request.content))
            body = (b'{"response":"ok","done":true}\n' if provider == 'ollama' else
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')
            return httpx.Response(200, content=body)
        real_client = httpx.AsyncClient
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(**kw, transport=httpx.MockTransport(handler)))
        assert [part async for part in llm_client.stream_llm_async('test', model='qwen3:8b')] == ['ok']
    asyncio.run(run())
    if provider == 'vllm':
        assert captured['model'] == 'served-model'
        assert captured['repetition_penalty'] == 1.18
    else:
        assert captured['options']['repeat_penalty'] == 1.18
        assert captured['options']['repeat_last_n'] == 256


@pytest.mark.parametrize('event', [
    {}, {'choices': None}, {'choices': {}},
    {'choices': [{'delta': {'content': False}}]},
    {'choices': [{'delta': {'content': []}}]},
])
def test_async_vllm_malformed_event_cannot_finish_successfully(monkeypatch, event):
    import json
    monkeypatch.setenv('LLM_PROVIDER', 'vllm')
    monkeypatch.setenv('VLLM_MODEL', 'served-model')
    async def run():
        async def handler(request):
            return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n')
        real_client = httpx.AsyncClient
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(**kw, transport=httpx.MockTransport(handler)))
        with pytest.raises(llm_client.LLMError):
            _ = [part async for part in llm_client.stream_llm_async('test')]
    asyncio.run(run())
