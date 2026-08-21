const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000')
  .replace(/\/$/, '')

async function describeHttpError(response) {
  try {
    const payload = await response.json()
    return payload?.error?.message || payload?.detail || payload?.message || response.statusText
  } catch {
    return response.statusText || '서버 응답을 처리하지 못했습니다.'
  }
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

export function checkBackend(signal) {
  return apiFetch('/health', { signal })
}

export function createAgent({ name, description }, signal) {
  return apiFetch('/agents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
    signal,
  })
}

export function uploadDocument(file, signal) {
  const formData = new FormData()
  formData.append('file', file)
  return apiFetch('/documents/parse', {
    method: 'POST',
    body: formData,
    signal,
  })
}

export function sendChat({ agentId, message, documentId = null, signal }) {
  if (!agentId) throw new Error('먼저 Backend에 등록된 페르소나를 선택해주세요.')
  return apiFetch(`/agents/${encodeURIComponent(agentId)}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, document_id: documentId }),
    signal,
  })
}

export { API_BASE_URL }
