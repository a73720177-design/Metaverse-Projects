import test from 'node:test'
import assert from 'node:assert/strict'
import { validateFiles, readWorkspace, newConversation } from './workspace-utils.mjs'

test('invalid storage and stale selections are safe', () => {
  assert.deepEqual(readWorkspace('{', [], []), { projectIds: [], selected: [] })
  assert.deepEqual(readWorkspace(JSON.stringify({ projectIds: ['a', 'a', 'other'], selected: ['p', 'other'] }), [{ document_id: 'a' }], [{ agent_id: 'p' }]), { projectIds: ['a'], selected: ['p'] })
})
test('uploads validate format and size without rejecting supported uppercase names', () => {
  const result = validateFiles([{ name: 'slides.PPTX', size: 100 }, { name: 'empty.pdf', size: 0 }, { name: 'x.exe', size: 100 }])
  assert.equal(result.accepted.length, 1)
  assert.equal(result.errors.length, 2)
})
test('questions own separate identities and message arrays', () => {
  const a = newConversation({ question_id: 'a', question: '첫 질문' })
  const b = newConversation({ question_id: 'b', question: '다른 질문' })
  assert.notEqual(a.conversationId, b.conversationId)
  assert.match(a.conversationId, /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/)
  a.messages.push({ text: '답변' })
  assert.equal(b.messages.length, 1)
  assert.equal(b.messages[0].text, '다른 질문')
})

 test('saved practice restores conversation identity and excludes trashed or other conversations', async () => {
  const { restorePracticeChats } = await import('./workspace-utils.mjs')
  const question = { question_id: 'q', conversation_id: 'c', question: '근거는?', sources: [] }
  const session = { response: { results: [{ persona_id: 'p', questions: [question] }] } }
  const record = { message_id: 'm', agent_id: 'p', conversation_id: 'c', message: '예상 질문: 근거는?\n발표자의 답변: 실험했습니다.\n답변을 평가하고 후속 질문을 해주세요.', answer: '추가 검증이 필요합니다.', created_at: '2026-01-01', sources: [], grounding: { checked: true, score: 0.5 } }
  const state = restorePracticeChats(session, [record, { ...record, message_id: 'other', conversation_id: 'other' }, { ...record, message_id: 'deleted', deleted_at: '2026-01-02' }]).p
  assert.equal(state.activeQuestionId, 'q')
  assert.equal(state.conversations.q.conversationId, 'c')
  assert.equal(state.conversations.q.messages.length, 3)
  assert.equal(state.conversations.q.messages[1].text, '실험했습니다.')
  assert.equal(state.conversations.q.messages[2].grounding.score, 0.5)
})
