import asyncio
import httpx
from app.integrations.llm.client import HttpLlmClient
from app.integrations.llm.generators import HttpChatGenerator
from app.models.persona import PersonaProfile
from app.models.chat import ChatRequest


def test_first_token_arrives_before_producer_finishes_and_close_reaches_transport():
    async def run():
        released = asyncio.Event()
        closed = asyncio.Event()
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'event: token\ndata: {"token":"<thi"}\n\n'
                yield b'event: token\ndata: {"token":"nk>private</think>first"}\n\n'
                await released.wait()
                yield b'event: done\ndata: {}\n\n'
            async def aclose(self):
                closed.set()
        async def handler(request):
            return httpx.Response(200, stream=Body())
        generator = HttpChatGenerator(HttpLlmClient(httpx.MockTransport(handler)))
        stream = generator.stream(PersonaProfile(name="평가자"), ChatRequest(message="hello"), None, [])
        assert await asyncio.wait_for(anext(stream), .5) == "first"
        assert not released.is_set()
        await stream.aclose()
        assert closed.is_set()
    asyncio.run(run())
