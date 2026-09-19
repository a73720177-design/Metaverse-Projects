// Thin client for the Backend. The running OpenAPI document and controller
// tests are the authoritative API contract.
// In development, Vite proxies this same-origin prefix to Backend. This keeps
// remote browsers from needing direct access to port 8000 and avoids CORS/PNA
// differences between machines. Deployments can still set an absolute URL.
import { createApiClient } from './api-client.mjs'
import { AppError, reportError } from './api-errors.mjs'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api-backend')
  .replace(/\/$/, '')

const client = createApiClient(API_BASE_URL)
const apiFetch = (path, options) => client.json(path, options)

export function getServiceStatus(signal) {
  return apiFetch('/health/services', { signal, timeoutMs: 15000 })
}

export function getDeveloperFeatureStatus(signal) {
  return apiFetch('/health/features', { signal, timeoutMs: 15000 })
}

function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Backend validates: username 3-32 chars [A-Za-z0-9_] (lowercased server-side),
// password 8-128 chars. Signup only creates the account — it does NOT return
// a token, so callers must follow up with login().
// -> { user_id, username, created_at }
export function signup({ username, password }, signal) {
  return apiFetch('/auth/signup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
    signal,
  })
}

// -> { access_token, token_type }
export function login({ username, password }, signal) {
  return apiFetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
    signal,
  })
}

// -> { user_id, username, created_at }
export function getCurrentUser(token, signal) {
  return apiFetch('/auth/me', {
    headers: authHeaders(token),
    signal,
  })
}

// Requires auth — Backend scopes agents to the caller. ->
// The UI collects a domain only. Backend legacy fields stay populated with
// deterministic defaults so existing DB migrations and saved personas remain compatible.
export function createAgent({ field, model = 'qwen3:4b', documentIds = [] }, token, signal) {
  const normalizedField = field.trim()
  return apiFetch('/agents', {
    // Local 4B/9B generation can exceed the common 30 second API deadline,
    // especially on CPU. Keep the UI request alive so it cannot look failed
    // while Backend is still creating and saving the persona.
    timeoutMs: 900000,
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({
      name: `${normalizedField.slice(0, 94)} 평가자`,
      description: normalizedField,
      model,
      document_ids: documentIds,
    }),
    signal,
  })
}

export function listDocuments(token, signal) {
  return apiFetch('/documents', { headers: authHeaders(token), signal })
}

export function deleteDocument(documentId, token, signal) {
  return apiFetch(`/documents/${encodeURIComponent(documentId)}`, {
    method: 'DELETE',
    headers: authHeaders(token),
    signal,
  })
}

// Requires auth — Backend scopes documents to the caller. ->
// { document_id, filename, document_type, sections, full_text }
export function uploadDocument(file, token, signal) {
  const formData = new FormData()
  formData.append('file', file)
  return apiFetch('/documents/parse', {
    timeoutMs: 900000,
    method: 'POST',
    headers: authHeaders(token),
    body: formData,
    signal,
  })
}

// Streams token events immediately and resolves with the persisted
// ChatHistoryItem from the final `done` event.
export async function streamChat({
  agentId,
  message,
  documentId = null,
  documentIds = [],
  conversationId = null,
  responseDetail = 'detailed',
  model = 'qwen3:4b',
  token,
  signal,
  onToken,
}) {
  if (!agentId) throw reportError(new AppError('먼저 질문자를 선택해주세요.', { code: 'validation_error' }))
  return client.stream(
      `/agents/${encodeURIComponent(agentId)}/chat/stream`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
        body: JSON.stringify({
          message,
          document_id: documentId,
          document_ids: documentIds,
          conversation_id: conversationId,
          response_detail: responseDetail,
          model,
        }),
        signal,
      }, onToken,
  )
}

export function updateAgentDocuments(agentId, documentIds, token, signal) {
  return apiFetch(`/agents/${encodeURIComponent(agentId)}/documents`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ document_ids: documentIds }),
    signal,
  })
}

export function updateAgent(agentId, { field, model = 'qwen3:4b', documentIds = [] }, token, signal) {
  const normalizedField = field.trim()
  return apiFetch(`/agents/${encodeURIComponent(agentId)}`, {
    timeoutMs: 900000,
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({
      name: `${normalizedField.slice(0, 94)} 평가자`,
      description: normalizedField,
      model,
      document_ids: documentIds,
    }),
    signal,
  })
}

export function deleteAgent(agentId, token, signal) {
  return apiFetch(`/agents/${encodeURIComponent(agentId)}`, {
    method: 'DELETE',
    headers: authHeaders(token),
    signal,
  })
}

export function generateExpectedQuestions({ personaIds, presentationDocumentIds, questionCount = 5, model = 'qwen3:4b' }, token, signal) {
  return apiFetch('/practice/questions', {
    // CPU-only laptop profile generates personas sequentially to avoid Ollama
    // memory contention. Four personas can legitimately take over five minutes.
    timeoutMs: 900000,
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({
      persona_ids: personaIds,
      presentation_document_ids: presentationDocumentIds,
      question_count_per_persona: questionCount,
      model,
    }),
    signal,
  })
}

// -> PersonaHistoryItem[] (active personas only — Backend excludes trashed ones)
export function listAgents(token, signal) {
  return apiFetch('/agents', { headers: authHeaders(token), signal })
}

// Moves a persona to Backend's trash (soft delete) -> PersonaHistoryItem
export function trashAgent(agentId, token, signal) {
  return apiFetch(`/agents/${encodeURIComponent(agentId)}`, {
    method: 'DELETE',
    headers: authHeaders(token),
    signal,
  })
}

// -> PersonaHistoryItem[]
export function listTrashedAgents(token, signal) {
  return apiFetch('/agents/trash', { headers: authHeaders(token), signal })
}

// -> PersonaHistoryItem (restored, deleted_at cleared)
export function restoreAgent(agentId, token, signal) {
  return apiFetch(`/agents/trash/${encodeURIComponent(agentId)}/restore`, {
    method: 'POST',
    headers: authHeaders(token),
    signal,
  })
}

// Only works on an already-trashed persona. -> null (204 No Content)
export function permanentlyDeleteAgent(agentId, token, signal) {
  return apiFetch(`/agents/trash/${encodeURIComponent(agentId)}`, {
    method: 'DELETE',
    headers: authHeaders(token),
    signal,
  })
}

// -> ChatHistoryItem[] (active chat messages only, across all of the caller's personas)
export function listChats(token, signal) {
  return apiFetch('/chats', { headers: authHeaders(token), signal })
}

// Moves one Q&A record to Backend's trash (soft delete) -> ChatHistoryItem
export function trashChat(messageId, token, signal) {
  return apiFetch(`/chats/${encodeURIComponent(messageId)}`, {
    method: 'DELETE',
    headers: authHeaders(token),
    signal,
  })
}

// -> ChatHistoryItem[]
export function listTrashedChats(token, signal) {
  return apiFetch('/trash/chats', { headers: authHeaders(token), signal })
}

// -> ChatHistoryItem (restored, deleted_at cleared)
export function restoreChat(messageId, token, signal) {
  return apiFetch(`/trash/chats/${encodeURIComponent(messageId)}/restore`, {
    method: 'POST',
    headers: authHeaders(token),
    signal,
  })
}

// Only works on an already-trashed chat. -> null (204 No Content)
export function permanentlyDeleteChat(messageId, token, signal) {
  return apiFetch(`/trash/chats/${encodeURIComponent(messageId)}`, {
    method: 'DELETE',
    headers: authHeaders(token),
    signal,
  })
}

// Creates (or returns the cached) summary for a document. Same
// (documentId, agentId, style) combination is cached server-side; pass
// refresh: true to force regeneration. -> SummaryResult
export function createSummary(documentId, { style = 'brief', agentId = null, refresh = false } = {}, token, signal) {
  const query = refresh ? '?refresh=true' : ''
  return apiFetch(`/documents/${encodeURIComponent(documentId)}/summary${query}`, {
    timeoutMs: 180000,
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ style, agent_id: agentId }),
    signal,
  })
}

// Fetches the cached default (brief, no persona) summary. -> SummaryResult
export function getSummary(documentId, token, signal) {
  return apiFetch(`/documents/${encodeURIComponent(documentId)}/summary`, {
    headers: authHeaders(token),
    signal,
  })
}

export function listPracticeSessions(token, signal) {
  return apiFetch('/practice/sessions', { headers: authHeaders(token), signal })
}

export function getPracticeSession(id, token, signal) {
  return apiFetch(`/practice/sessions/${encodeURIComponent(id)}`, { headers: authHeaders(token), signal })
}

export function listReviews(token, signal) {
  return apiFetch('/reviews', { headers: authHeaders(token), signal })
}

export function getReview(id, token, signal) {
  return apiFetch(`/reviews/${encodeURIComponent(id)}`, { headers: authHeaders(token), signal })
}

export function createReview(agentId, documentId, token, model = 'qwen3:4b', signal) {
  return apiFetch(`/agents/${encodeURIComponent(agentId)}/reviews`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ document_id: documentId, model }), timeoutMs: 900000, signal,
  })
}
