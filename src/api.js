// Thin client for the real Backend (see backend/docs/INTEGRATION_CONTRACTS.md
// and backend/app/controllers/*.py in the Metaverse-Projects repo for the
// authoritative contract). SSE streaming and multi-turn history are not
// supported by Backend yet.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000')
  .replace(/\/$/, '')

// Backend errors are `{ error: { code, message } }`; some paths (validation,
// FastAPI defaults) instead send `{ detail }` or `{ message }`.
async function describeHttpError(response) {
  try {
    const payload = await response.json()
    return payload?.error?.message || payload?.detail || payload?.message || response.statusText
  } catch {
    return response.statusText || '서버 응답을 처리하지 못했습니다.'
  }
}

function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function apiFetch(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, options)
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('Backend에 연결할 수 없습니다. 서버 주소와 실행 상태를 확인해주세요.')
  }

  if (!response.ok) {
    const message = await describeHttpError(response)
    throw new Error(`${message} (${response.status})`)
  }
  if (response.status === 204) return null
  return response.json()
}

export function checkServices(signal) {
  return apiFetch('/health/services', { signal })
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
// { agent_id, name, description, role, expertise, evaluation_style }
export function createAgent({ name, description }, token, signal) {
  return apiFetch('/agents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ name, description }),
    signal,
  })
}

// Requires auth — returns only agents owned by the caller.
export function getAgents(token, signal) {
  return apiFetch('/agents', {
    headers: authHeaders(token),
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

// Requires auth — Backend scopes documents to the caller. ->
// { document_id, filename, document_type, sections, full_text }
export function uploadDocument(file, token, signal) {
  const formData = new FormData()
  formData.append('file', file)
  return apiFetch('/documents/parse', {
    method: 'POST',
    headers: authHeaders(token),
    body: formData,
    signal,
  })
}

// Requires auth — Backend only lets you chat with agents/documents you own.
// -> { message_id, agent_id, answer, sources }
export function sendChat({ agentId, message, documentId = null, token, signal }) {
  if (!agentId) throw new Error('먼저 Backend에 등록된 페르소나를 선택해주세요.')
  return apiFetch(`/agents/${encodeURIComponent(agentId)}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ message, document_id: documentId }),
    signal,
  })
}

export { API_BASE_URL }
