import test from 'node:test'
import assert from 'node:assert/strict'
import { chatPromptPreview, documentDeletePrompt, groupChatsByConversation, validateFiles, readWorkspace, newConversation, restorePracticeChats, reviewableDocuments, shouldSubmitChatKey } from './workspace-utils.mjs'

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

test('chat enter submits while shift-enter and Korean composition keep editing', () => {
  assert.equal(shouldSubmitChatKey({ key: 'Enter' }), true)
  assert.equal(shouldSubmitChatKey({ key: 'Enter', shiftKey: true }), false)
  assert.equal(shouldSubmitChatKey({ key: 'Enter', isComposing: true }), false)
  assert.equal(shouldSubmitChatKey({ key: 'Enter', keyCode: 229 }), false)
  assert.equal(shouldSubmitChatKey({ key: 'a' }), false)
})

test('source deletion prompt names the file and clearly asks for confirmation', () => {
  assert.equal(documentDeletePrompt('발표자료.pdf'), '정말 "발표자료.pdf" 을 삭제하시겠습니까?')
})

test('material review only offers selected presentation documents', () => {
  const documents = [
    { document_id: 'presentation', filename: '발표.pdf', text_length: 120 },
    { document_id: 'persona', filename: '교수 참고.pdf', text_length: 240 },
    { document_id: 'empty', filename: '빈 발표.pdf', text_length: 0 },
  ]
  assert.deepEqual(
    reviewableDocuments(documents, ['presentation', 'empty', 'persona'], ['persona'])
      .map((document) => document.document_id),
    ['presentation'],
  )
})

test('material review excludes a persona source even when stale workspace state marks it as presentation', () => {
  const documents = [
    { document_id: 'presentation', filename: '발표.pdf', full_text: '발표 본문' },
    { document_id: 'shared-stale', filename: '질문자 기준.pdf', full_text: '평가 기준' },
  ]

  assert.deepEqual(
    reviewableDocuments(documents, ['presentation', 'shared-stale'], ['shared-stale'])
      .map((document) => document.document_id),
    ['presentation'],
  )
})

test('saved practice restores conversation identity and excludes trashed or other conversations', () => {
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

test('saved practice can focus the exact conversation selected from history', () => {
  const questions = [
    { question_id: 'q1', conversation_id: 'c1', question: '첫 질문', sources: [] },
    { question_id: 'q2', conversation_id: 'c2', question: '둘째 질문', sources: [] },
  ]
  const session = { response: { results: [{ persona_id: 'p', questions }] } }
  assert.equal(restorePracticeChats(session, [], 'c2').p.activeQuestionId, 'q2')
})

test('chat history groups turns and extracts readable prompt text', () => {
  const rows = [
    { message_id: 'm2', conversation_id: 'c1', agent_id: 'p', created_at: '2026-01-02', message: '후속 답변', deleted_at: null },
    { message_id: 'm1', conversation_id: 'c1', agent_id: 'p', created_at: '2026-01-01', message: '첫 답변', deleted_at: null },
    { message_id: 'm3', conversation_id: 'c2', agent_id: 'p', created_at: '2026-01-03', message: '다른 대화', deleted_at: null },
  ]
  const groups = groupChatsByConversation(rows)
  assert.equal(groups.length, 2)
  assert.equal(groups[1].messages[0].message_id, 'm1')
  assert.deepEqual(chatPromptPreview('예상 질문: 근거는?\n발표자의 답변: 실험했습니다.\n답변을 평가하고 후속 질문을 해주세요.'), { question: '근거는?', answer: '실험했습니다.' })
})
