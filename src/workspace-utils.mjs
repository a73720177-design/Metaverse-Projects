export const MAX_FILE_BYTES = 25 * 1024 * 1024
const SUPPORTED_EXTENSIONS = new Set(['pdf', 'pptx', 'docx'])

export function validateFiles(files) {
  const accepted = []
  const errors = []
  for (const file of files) {
    if (!SUPPORTED_EXTENSIONS.has(file.name.split('.').pop()?.toLowerCase())) {
      errors.push(`${file.name}: PDF, PPTX, DOCX 파일을 선택해주세요.`)
    } else if (!file.size || file.size > MAX_FILE_BYTES) {
      errors.push(`${file.name}: 빈 파일이거나 파일당 25MB 제한을 초과했습니다.`)
    } else accepted.push(file)
  }
  return { accepted, errors }
}

// randomUUID is unavailable in non-HTTPS LAN browsers; getRandomValues still works.
export function newConversationId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function readWorkspace(value, documents, personas) {
  let saved
  try { saved = JSON.parse(value || '{}') } catch { saved = {} }
  const documentIds = new Set(documents.map((doc) => doc.document_id))
  const personaIds = new Set(personas.map((persona) => persona.agent_id))
  return {
    projectIds: [...new Set(Array.isArray(saved?.projectIds) ? saved.projectIds : [])].filter((id) => documentIds.has(id)),
    selected: [...new Set(Array.isArray(saved?.selected) ? saved.selected : [])].filter((id) => personaIds.has(id)).slice(0, 4),
  }
}

export function newConversation(question) {
  return {
    conversationId: question.conversation_id || newConversationId(), question, input: '', sending: false,
    messages: [{ id: `q-${question.question_id}`, role: 'persona', text: question.question, sources: question.sources }],
    forceScroll: true,
  }
}

export function restorePracticeChats(session, history) {
  return Object.fromEntries(session.response.results.map((result) => {
    const conversations = Object.fromEntries(result.questions.map((question) => {
      const conversation = newConversation(question)
      const records = history.filter((item) => item.agent_id === result.persona_id &&
        item.conversation_id === conversation.conversationId && !item.deleted_at)
        .sort((a, b) => a.created_at.localeCompare(b.created_at))
      for (const record of records) {
        const prefix = `예상 질문: ${question.question}\n발표자의 답변: `
        const suffix = '\n답변을 평가하고 후속 질문을 해주세요.'
        const text = record.message.startsWith(prefix) && record.message.endsWith(suffix)
          ? record.message.slice(prefix.length, -suffix.length) : record.message
        conversation.messages.push({ id: `u-${record.message_id}`, role: 'user', text })
        conversation.messages.push({ id: record.message_id, role: 'persona', text: record.answer,
          sources: record.sources, grounding: record.grounding, timing: record.timing })
      }
      return [question.question_id, conversation]
    }))
    return [result.persona_id, { activeQuestionId: result.questions[0]?.question_id || null, conversations }]
  }))
}
