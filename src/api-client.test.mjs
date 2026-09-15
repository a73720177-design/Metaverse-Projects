import test, { beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { createApiClient } from './api-client.mjs'
import { AppError, clearErrors, diagnosticText, getErrors, reportError, reportLocalError } from './api-errors.mjs'

beforeEach(clearErrors)
const jsonResponse = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
const withResponse = (response) => createApiClient('/api', { fetchImpl: async () => response })
const streamResponse = (parts) => new Response(new ReadableStream({ start(controller) { parts.forEach((part) => controller.enqueue(new TextEncoder().encode(part))); controller.close() } }), { headers: { 'Content-Type': 'text/event-stream', 'X-Request-ID': 'stream-id' } })

test('successful JSON and 204 responses do not create error records', async () => {
  assert.deepEqual(await withResponse(jsonResponse({ ok: true })).json('/health'), { ok: true })
  assert.equal(await withResponse(new Response(null, { status: 204 })).json('/agents/1'), null)
  assert.equal(getErrors().length, 0)
})

test('wrong login and expired authenticated requests stay distinguishable', async () => {
  await assert.rejects(withResponse(jsonResponse({ error: { code: 'http_401', message: '아이디 또는 비밀번호가 올바르지 않습니다.' } }, 401)).json('/auth/login', { method: 'POST', body: 'password=do-not-record' }), { code: 'invalid_credentials' })
  assert.equal(getErrors()[0].authenticated, false)
  await assert.rejects(withResponse(jsonResponse({ detail: 'Invalid credentials' }, 401)).json('/documents', { headers: { Authorization: 'Bearer secret' } }), { code: 'session_expired' })
  assert.equal(getErrors()[0].authenticated, true)
  assert.doesNotMatch(JSON.stringify(getErrors()), /do-not-record|Bearer secret/)
})

test('validation fields preserve locations but never input or ctx', async () => {
  const response = jsonResponse({ detail: [{ loc: ['body', 'password'], msg: '최소 8자입니다.', type: 'string_too_short', input: 'SECRET', ctx: { password: 'SECRET' } }] }, 422)
  await assert.rejects(withResponse(response).json('/auth/signup'), { status: 422 })
  assert.equal(getErrors()[0].fields[0].label, '비밀번호')
  assert.doesNotMatch(diagnosticText(getErrors()[0]), /SECRET|input|ctx/)
})

test('structured DB errors and request ID survive transport', async () => {
  await assert.rejects(withResponse(jsonResponse({ error: { code: 'database_read_only', message: '읽기 전용', request_id: 'req-1' } }, 503)).json('/documents?token=secret'), { code: 'database_read_only' })
  assert.equal(getErrors()[0].requestId, 'req-1')
  assert.equal(getErrors()[0].path, '/api/documents')
  assert.match(getErrors()[0].hint, /읽기 전용/)
})

test('proxy HTML errors use safe fallback and Retry-After is retained', async () => {
  await assert.rejects(withResponse(new Response('<html>private proxy info</html>', { status: 502 })).json('/health'), { status: 502 })
  assert.doesNotMatch(getErrors()[0].message, /html|private/)
  await assert.rejects(withResponse(jsonResponse({ detail: '요청 제한' }, 429, { 'Retry-After': '45' })).json('/auth/login'), { status: 429 })
  assert.equal(getErrors()[0].retryAfter, 45)
})

test('malformed successful JSON is reported as an invalid response', async () => {
  await assert.rejects(withResponse(new Response('<html/>')).json('/agents'), { code: 'invalid_response' })
})

test('network errors are reported and duplicate catches are not duplicated', async () => {
  const client = createApiClient('/api', { fetchImpl: async () => { throw new TypeError('fetch failed') } })
  await client.json('/auth/me').catch(reportError)
  assert.equal(getErrors().length, 1)
  assert.equal(getErrors()[0].code, 'network_error')
})

test('timeouts are errors; user cancellation stays silent', async () => {
  const fetchImpl = (_url, { signal }) => new Promise((_resolve, reject) => {
    const abort = () => reject(new DOMException('aborted', 'AbortError'))
    if (signal.aborted) abort()
    else signal.addEventListener('abort', abort, { once: true })
  })
  const client = createApiClient('/api', { fetchImpl, timeoutMs: 10 })
  await assert.rejects(client.json('/agents'), { code: 'request_timeout' })
  clearErrors()
  const controller = new AbortController()
  const pending = client.json('/agents', { signal: controller.signal })
  controller.abort()
  await assert.rejects(pending, { name: 'AbortError' })
  assert.equal(getErrors().length, 0)
})

test('split SSE chunks and CRLF retain tokens and final result', async () => {
  const tokens = []
  const response = streamResponse([': ping\r\n\r\nevent: tok', 'en\r\ndata: {"token":"안녕."}\r\n\r\n', 'event: done\ndata: {"message_id":"m1","answer":"안녕."}\n\n'])
  const result = await withResponse(response).stream('/chat', {}, (token) => tokens.push(token))
  assert.equal(result.answer, '안녕.')
  assert.equal(tokens.join(''), '안녕.')
  assert.equal(getErrors().length, 0)
})

test('SSE error after HTTP 200 displays code and request ID', async () => {
  const response = streamResponse(['event: error\ndata: {"code":"database_unavailable","message":"저장 실패","request_id":"s1"}\n\n'])
  await assert.rejects(withResponse(response).stream('/chat', {}), { code: 'database_unavailable' })
  assert.equal(getErrors()[0].status, null)
  assert.equal(getErrors()[0].requestId, 's1')
})

test('missing final SSE event, broken JSON and invalid done are visible', async () => {
  for (const [body, code] of [
    ['event: token\ndata: {"token":"partial"}\n\n', 'stream_interrupted'],
    ['event: token\ndata: {broken}\n\n', 'invalid_response'],
    ['event: done\ndata: {}\n\n', 'invalid_response'],
  ]) await assert.rejects(withResponse(streamResponse([body])).stream('/chat', {}), { code })
  assert.equal(getErrors().length, 3)
})

test('local errors are bounded and copied diagnostics redact credentials', () => {
  for (let i = 0; i < 25; i++) reportLocalError(`파일 오류 ${i}`, 'file_validation')
  assert.equal(getErrors().length, 20)
  reportError(new AppError('password=secret Bearer token postgresql://user:secret@host/db'))
  assert.doesNotMatch(diagnosticText(getErrors()[0]), /secret|Bearer token/)
})

test('common HTTP failures always have a usable message and status', async () => {
  for (const status of [400, 403, 404, 405, 408, 409, 413, 415, 422, 429, 500, 502, 503, 504]) {
    await assert.rejects(withResponse(jsonResponse({}, status)).json('/documents'), (error) => {
      assert.equal(error.status, status)
      assert.ok(error.message.length > 5)
      assert.ok(error.hint.length > 5)
      return true
    })
  }
})

test('schema mismatch exposes missing names and malformed fields remain safe', async () => {
  await assert.rejects(withResponse(jsonResponse({ error: { code: 'DB_SCHEMA_MISMATCH', contract: { missing: { chat_messages: ['timing'] } } } }, 503)).json('/health/db'))
  assert.equal(getErrors()[0].fields[0].field, 'chat_messages')
  assert.match(getErrors()[0].fields[0].message, /timing/)
  await assert.rejects(withResponse(jsonResponse({ error: { code: 'validation_error', fields: [null, 'bad', { field: 'name', message: '필수' }] } }, 422)).json('/agents'), { code: 'validation_error' })
  assert.equal(getErrors()[0].fields.length, 1)
})

test('idle SSE times out and a stalled body can be cancelled', async () => {
  const fetchImpl = async (_url, { signal }) => new Response(new ReadableStream({
    start(controller) { signal.addEventListener('abort', () => controller.error(new DOMException('abort', 'AbortError')), { once: true }) },
  }), { headers: { 'Content-Type': 'text/event-stream' } })
  const client = createApiClient('/api', { fetchImpl, streamIdleMs: 10 })
  await assert.rejects(client.stream('/chat', {}), { code: 'request_timeout' })
  clearErrors()
  const controller = new AbortController()
  const pending = client.stream('/chat', { signal: controller.signal })
  controller.abort()
  await assert.rejects(pending, { name: 'AbortError' })
  assert.equal(getErrors().length, 0)
})

test('legacy stream error and read failures are categorized', async () => {
  await assert.rejects(withResponse(streamResponse(['event: error\ndata: {"message":"생성 실패"}\n\n'])).stream('/chat', {}), { code: 'stream_error' })
  const failed = new Response(new ReadableStream({ start(controller) { controller.error(new TypeError('connection reset')) } }), { headers: { 'Content-Type': 'text/event-stream' } })
  await assert.rejects(withResponse(failed).stream('/chat', {}), { code: 'stream_interrupted' })
})
