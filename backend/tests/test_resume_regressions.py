import asyncio
import json
from uuid import uuid4

import pytest

from app.controllers.chat_controller import _encode_sse
from app.integrations.llm.response_sanitizer import clean_model_text, extract_json_object, sanitize_llm_payload
from app.models.chat import ChatHistoryItem
from app.repositories.chat_repository import InMemoryChatRepository


def test_question_history_isolated_by_owner_agent_conversation_and_trash():
    async def check():
        repo = InMemoryChatRepository()
        owner, agent, first, second = [uuid4() for _ in range(4)]
        for user, persona, thread in [(owner, agent, first), (owner, agent, second), (uuid4(), agent, first), (owner, uuid4(), first), (owner, agent, None)]:
            await repo.save(ChatHistoryItem(owner_id=user, agent_id=persona, conversation_id=thread, message='question', answer='answer'))
        found = await repo.list_recent(owner, agent, 10, first)
        assert len(found) == 1
        assert len(await repo.list_recent(owner, agent, 10)) == 1
        await repo.set_deleted(found[0].message_id, owner, deleted=True)
        assert await repo.list_recent(owner, agent, 10, first) == []
        assert len(await repo.list_recent(owner, agent, 10, second)) == 1
    asyncio.run(check())


def test_sanitizer_nested_incomplete_and_source_preservation():
    assert clean_model_text('<think>private<analysis>hidden</analysis>hidden</think>공개') == '공개'
    assert clean_model_text('공개<think>unfinished') == '공개'
    assert clean_model_text('private</think>공개') == '공개'
    assert extract_json_object('<think>{"answer":"private"}</think>{"answer":"public"}') == {'answer': 'public'}
    with pytest.raises(json.JSONDecodeError):
        extract_json_object('{"answer":"one"}{"answer":"two"}')
    assert sanitize_llm_payload({'reasoning': 'secret', 'answer': '<think>x</think>yes', 'excerpt': '<think>source</think>'}) == {'answer': 'yes', 'excerpt': '<think>source</think>'}


def test_sse_heartbeat_and_disconnect_cancel_upstream():
    async def check():
        closed = asyncio.Event()
        async def upstream():
            try:
                await asyncio.Event().wait()
                yield {}
            finally:
                closed.set()
        stream = _encode_sse(upstream(), heartbeat_seconds=0.001)
        assert 'connected' in await anext(stream)
        assert 'keep-alive' in await anext(stream)
        await stream.aclose()
        assert closed.is_set()
    asyncio.run(check())
