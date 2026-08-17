// Thin client for the separately-running backend (LLM + DB).
// Point VITE_API_BASE_URL at your backend — see .env.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// Assumes an SSE-style stream: lines of `data: {"delta":"..."}` ending with
// `data: [DONE]`. If a line isn't JSON, its raw text is treated as the delta.
// Adjust the parsing below once you wire this up to your real backend's format.
export async function streamChat({ message, persona, signal, onDelta, onDone, onError }) {
  try {
    const res = await fetch(`${API_BASE_URL}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, persona }),
      signal,
    })

    if (!res.ok || !res.body) {
      throw new Error(`서버 응답 오류: ${res.status}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data:')) continue
        const payload = trimmed.slice(5).trim()
        if (payload === '[DONE]') {
          onDone && onDone()
          return
        }
        try {
          const json = JSON.parse(payload)
          if (json.delta) onDelta(json.delta)
        } catch (e) {
          if (payload) onDelta(payload)
        }
      }
    }

    onDone && onDone()
  } catch (err) {
    if (err.name === 'AbortError') return
    onError && onError(err)
  }
}
