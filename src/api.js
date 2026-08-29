// Thin client for the Backend. The running OpenAPI document and controller
// tests are the authoritative API contract.
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

// Streams token events immediately and resolves with the persisted
// ChatHistoryItem from the final `done` event.
export async function streamChat({
  agentId,
  message,
  documentId = null,
  token,
  signal,
  onToken,
}) {
  if (!agentId) throw new Error('먼저 Backend에 등록된 페르소나를 선택해주세요.')

  let response
  try {
    response = await fetch(
      `${API_BASE_URL}/agents/${encodeURIComponent(agentId)}/chat/stream`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
        body: JSON.stringify({ message, document_id: documentId }),
        signal,
      },
    )
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('Backend에 연결할 수 없습니다. 서버 주소와 실행 상태를 확인해주세요.')
  }

  if (!response.ok) {
    const errorMessage = await describeHttpError(response)
    throw new Error(`${errorMessage} (${response.status})`)
  }
  if (!response.body) throw new Error('Backend가 스트리밍 응답을 제공하지 않았습니다.')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completedItem = null

  const handleEvent = (block) => {
    let event = 'message'
    const dataLines = []
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
    }
    if (dataLines.length === 0) return

    let data
    try {
      data = JSON.parse(dataLines.join('\n'))
    } catch {
      throw new Error('Backend 스트리밍 응답 형식이 올바르지 않습니다.')
    }

    if (event === 'token') onToken?.(data.token || '')
    if (event === 'done') completedItem = data
    if (event === 'error') throw new Error(data.message || '채팅 스트리밍 중 오류가 발생했습니다.')
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    blocks.forEach(handleEvent)
    if (done) break
  }
  if (buffer.trim()) handleEvent(buffer)
  if (!completedItem) throw new Error('Backend 스트리밍이 완료 결과 없이 종료되었습니다.')
  return completedItem
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
