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


def test_endpoint_filters_reasoning_incrementally_before_done(monkeypatch):
    async def run():
        closed = asyncio.Event()
        async def provider(*args, **kwargs):
            try:
                for text in ['<thi', 'nk>private', '</think>첫 응답']:
                    yield text
                await asyncio.Event().wait()
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
