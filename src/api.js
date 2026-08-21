// Thin client for the separately-running backend (LLM + DB).
// Point VITE_API_BASE_URL at your backend — see .env.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// Assumed request/response shape — adjust once you wire this up to your real
// backend's auth endpoint:
//   POST {API_BASE_URL}/api/auth/login   body: { email, password }
//   200  -> { token: string, user: { name: string, email: string } }
//   401  -> { message: string }  (bad credentials)
export async function login({ email, password }) {
  const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })

  let data = null
  try {
    data = await res.json()
  } catch (e) {
    // non-JSON error body — fall through to the generic message below
  }

  if (!res.ok) {
    throw new Error((data && data.message) || `로그인에 실패했어요 (${res.status}).`)
  }
  if (!data || !data.token) {
    throw new Error('서버 응답에 인증 토큰이 없어요.')
  }
  return data
}

// Reads a failed response's body (JSON `{message}` or plain text) so callers
// get more than just a bare status code.
async function describeHttpError(res) {
  let detail = ''
  try {
    const text = await res.text()
    try {
      const json = JSON.parse(text)
      detail = json.message || text
    } catch (e) {
      detail = text
    }
  } catch (e) {
    // body already consumed / unreadable — fall back to the status alone
  }
  return detail ? `서버 응답 오류 (${res.status}): ${detail}` : `서버 응답 오류: ${res.status}`
}

// SSE-style stream, one event per line: `field: value` lines, most commonly
// `data: {"delta": "..."}`. We dispatch each `data:` line the moment it
// arrives (rather than batching until a blank line) because most minimal
// LLM-streaming backends — including the one this client assumes — write
// `data: {...}\n` per chunk without the blank-line event separator that the
// full SSE spec technically requires. `event:` tags the type of the *next*
// `data:` line (default "message"); `event: error` + `data: {"message":...}`
// reports a mid-stream failure instead of a delta. `id:`/`retry:` are kept
// for reconnect. Adjust below if your backend's format differs.
async function readEventStream(res, { onDelta, onServerError }) {
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finished = false
  let lastEventId = null
  let retryMs = null
  let eventType = 'message'

  const handlePayload = (payload) => {
    const type = eventType
    eventType = 'message'
    if (!payload) return

    if (type === 'error') {
      let message = payload
      try {
        message = JSON.parse(payload).message || payload
      } catch (e) {
        // plain-text error payload — used as-is
      }
      onServerError(new Error(message))
      finished = true
      return
    }

    if (payload === '[DONE]') {
      finished = true
      return
    }

    // Must be `{"delta": "..."}` JSON — anything else is a protocol error,
    // not text to silently show the user as if the model said it.
    try {
      const json = JSON.parse(payload)
      if (typeof json.delta === 'string') onDelta(json.delta)
    } catch (e) {
      onServerError(new Error(`서버에서 알 수 없는 형식의 응답을 받았어요: ${payload.slice(0, 200)}`))
      finished = true
    }
  }

  const handleLine = (line) => {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith(':')) return // blank / comment line
    const sep = trimmed.indexOf(':')
    const field = sep === -1 ? trimmed : trimmed.slice(0, sep)
    let value = sep === -1 ? '' : trimmed.slice(sep + 1)
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'data') handlePayload(value)
    else if (field === 'event') eventType = value || 'message'
    else if (field === 'id') lastEventId = value
    else if (field === 'retry') { const n = Number(value); if (!Number.isNaN(n)) retryMs = n }
  }

  while (!finished) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split('\n')
    buffer = lines.pop() ?? '' // last line may still be incomplete — keep buffering

    for (const line of lines) {
      handleLine(line)
      if (finished) break
    }
  }

  // Flush the decoder and process whatever line the server didn't
  // newline-terminate before closing the stream.
  buffer += decoder.decode()
  if (!finished && buffer.trim()) handleLine(buffer)

  return { finished, lastEventId, retryMs }
}

// `messages` is the full conversation so far (including the new user
// message), as [{ role: 'user' | 'assistant', content: string }] — this lets
// the backend answer with the prior turns as context instead of only the
// latest message.
export async function streamChat({ messages, persona, token, signal, onDelta, onDone, onError }) {
  const MAX_RECONNECTS = 2
  let attempt = 0
  let lastEventId = null

  while (true) {
    try {
      const res = await fetch(`${API_BASE_URL}/api/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(lastEventId ? { 'Last-Event-ID': lastEventId } : {}),
        },
        body: JSON.stringify({ messages, persona }),
        signal,
      })

      if (!res.ok) throw new Error(await describeHttpError(res))
      if (!res.body) throw new Error('서버가 스트리밍 응답을 지원하지 않아요.')

      let serverError = null
      const result = await readEventStream(res, {
        onDelta,
        onServerError: (err) => { serverError = err },
      })

      if (serverError) { onError && onError(serverError); return }
      if (result.finished) { onDone && onDone(); return }

      // Stream closed without [DONE] or an error event — a dropped
      // connection. Reconnect only if the server told us it's safe to
      // (sent a `retry:` field) and we haven't retried too many times.
      if (result.retryMs == null || attempt >= MAX_RECONNECTS) {
        onDone && onDone()
        return
      }
      lastEventId = result.lastEventId || lastEventId
      attempt += 1
      await new Promise((resolve) => setTimeout(resolve, result.retryMs))
      // loop and reconnect
    } catch (err) {
      if (err.name === 'AbortError') return
      onError && onError(err)
      return
    }
  }
}
