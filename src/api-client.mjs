import { AppError, fromPayload, reportError } from './api-errors.mjs'

// Every API operation, including streaming, goes through this boundary.
export function createApiClient(baseUrl, { fetchImpl = (...args) => fetch(...args), timeoutMs = 30000, streamIdleMs = 60000 } = {}) {
  async function request(path, options = {}, consume) {
    const { signal, timeoutMs: deadline = timeoutMs, ...init } = options
    const controller = new AbortController()
    const context = { path: `${baseUrl}${path}`, method: init.method || 'GET', authenticated: new Headers(init.headers).has('Authorization') }
    let timedOut = false
    let timer
    const timeout = () => { timedOut = true; controller.abort() }
    const totalTimer = setTimeout(timeout, deadline)
    const resetTimer = (milliseconds = deadline) => {
      clearTimeout(timer)
      timer = setTimeout(timeout, milliseconds)
    }
    const abort = () => controller.abort()
    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) abort()
    try {
      const response = await fetchImpl(`${baseUrl}${path}`, { ...init, signal: controller.signal })
      context.status = response.status
      context.requestId = response.headers.get('X-Request-ID') || ''
      if (!response.ok) {
        let payload
        try { payload = await response.json() } catch (error) { if (controller.signal.aborted) throw error }
        const retry = response.headers.get('Retry-After')
        context.retryAfter = retry && /^\d+$/.test(retry) ? Number(retry) : null
        throw fromPayload(payload, context)
      }
      return await consume(response, context, resetTimer)
    } catch (error) {
      if (signal?.aborted && !timedOut) throw new DOMException('요청을 취소했습니다.', 'AbortError')
      let failure = error
      if (timedOut) failure = new AppError('응답 대기 시간이 초과되었습니다.', { ...context, code: 'request_timeout' })
      else if (!(error instanceof AppError)) {
        const offline = globalThis.navigator?.onLine === false
        failure = new AppError(offline ? '네트워크 연결이 끊겨 있습니다.' : '서버와 통신할 수 없습니다.', { ...context, code: offline ? 'offline' : 'network_error' })
      }
      reportError(failure)
      throw failure
    } finally {
      clearTimeout(timer)
      clearTimeout(totalTimer)
      signal?.removeEventListener('abort', abort)
    }
  }

  return {
    json(path, options) {
      return request(path, options, async (response, context) => {
        if (response.status === 204) return null
        try { return await response.json() }
        catch (error) {
          if (error.name === 'AbortError') throw error
          throw new AppError('서버 응답을 JSON으로 해석할 수 없습니다.', { ...context, code: 'invalid_response' })
        }
      })
    },
    stream(path, options, onToken) {
      return request(path, { timeoutMs: 300000, ...options }, async (response, context, resetTimer) => {
        if (!response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) {
          throw new AppError('서버가 채팅 스트리밍 응답을 반환하지 않았습니다.', { ...context, code: 'invalid_response' })
        }
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let completed = null
        let display = ''
        const flush = (force = false) => {
          if (!display || (!force && !/(?:\n|[.!?。！？]\s*)$/.test(display) && display.length < 80)) return
          try { onToken?.(display) } catch {
            throw new AppError('받은 답변을 화면에 표시하지 못했습니다.', { ...context, code: 'client_error' })
          }
          display = ''
        }
        const handle = (block) => {
          let event = 'message'
          const lines = []
          for (const line of block.split(/\r?\n/)) {
            if (line.startsWith('event:')) event = line.slice(6).trim()
            if (line.startsWith('data:')) lines.push(line.slice(5).trimStart())
          }
          if (!lines.length) return
          let data
          try { data = JSON.parse(lines.join('\n')) } catch {
            throw new AppError('채팅 스트리밍 응답 형식이 올바르지 않습니다.', { ...context, code: 'invalid_response' })
          }
          if (event === 'error') throw fromPayload(data, { ...context, status: null, code: 'stream_error' })
          if (event === 'token') {
            if (typeof data?.token !== 'string') throw new AppError('채팅 토큰 형식이 올바르지 않습니다.', { ...context, code: 'invalid_response' })
            display += data.token
            flush()
          }
          if (event === 'done') {
            if (typeof data?.answer !== 'string' || !data?.message_id) throw new AppError('채팅 완료 응답에 필수 값이 없습니다.', { ...context, code: 'invalid_response' })
            flush(true)
            completed = data
          }
        }
        try {
          resetTimer(streamIdleMs)
          while (!completed) {
            const { value, done } = await reader.read()
            resetTimer(streamIdleMs)
            buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
            const blocks = buffer.split(/\r?\n\r?\n/)
            buffer = blocks.pop() || ''
            for (const block of blocks) { handle(block); if (completed) break }
            if (buffer.length > 2000000) throw new AppError('채팅 응답 크기 제한을 초과했습니다.', { ...context, code: 'invalid_response' })
            if (done) break
          }
          if (!completed && buffer.trim()) handle(buffer)
          if (!completed) throw new AppError('완료 결과를 받기 전에 채팅 연결이 종료되었습니다.', { ...context, code: 'stream_interrupted' })
          return completed
        } catch (error) {
          if (error instanceof AppError || error?.name === 'AbortError') throw error
          throw new AppError('채팅 수신 중 서버와의 연결이 끊겼습니다.', { ...context, code: 'stream_interrupted' })
        } finally {
          await reader.cancel().catch(() => {})
          reader.releaseLock()
        }
      })
    },
  }
}
