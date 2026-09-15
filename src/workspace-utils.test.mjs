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
