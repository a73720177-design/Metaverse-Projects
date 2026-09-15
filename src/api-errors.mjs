const STATUS_MESSAGES = {
  400: '요청 내용을 확인해주세요.', 401: '로그인이 만료되었거나 인증 정보가 올바르지 않습니다.',
  403: '이 작업을 수행할 권한이 없습니다.', 404: '요청한 자료나 기능을 찾을 수 없습니다.',
  405: '서버가 이 요청 방식을 지원하지 않습니다.', 408: '요청 대기 시간이 초과되었습니다.',
  409: '이미 존재하거나 현재 상태와 충돌하는 요청입니다.', 413: '파일 크기가 업로드 제한을 초과했습니다.',
  415: '지원하지 않는 파일 형식입니다.', 422: '입력값이 올바르지 않습니다.',
  429: '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.',
  500: '서버에서 요청을 처리하는 중 오류가 발생했습니다.',
  502: '백엔드 또는 AI 서비스에서 정상 응답을 받지 못했습니다.',
  503: '서버 또는 연결된 서비스를 일시적으로 사용할 수 없습니다.',
  504: '서버 또는 AI 서비스의 응답 대기 시간이 초과되었습니다.',
}
const GUIDANCE = {
  invalid_credentials: '아이디와 비밀번호를 확인해주세요.',
  session_expired: '다시 로그인한 뒤 작업을 시도해주세요.',
  username_taken: '다른 아이디로 가입해주세요.',
  network_error: '백엔드 실행 상태와 Vite 프록시·서버 주소를 확인하세요. 브라우저가 요청을 차단한 경우 CORS 설정도 확인하세요.',
  offline: '인터넷 또는 로컬 네트워크 연결을 확인해주세요.',
  request_timeout: '서버 로그에서 처리 상태를 확인하세요. 생성·저장 요청은 이미 처리됐을 수 있으므로 결과 확인 후 다시 시도하세요.',
  database_unavailable: 'PostgreSQL 실행 상태와 백엔드의 DB 연결 설정을 확인하세요.',
  database_read_only: 'DB 연결이 읽기 전용인지 확인하세요. 쓰기가 가능한 DB 연결이 필요합니다.',
  database_schema_mismatch: '현재 코드에 필요한 DB 마이그레이션이 적용됐는지 확인하세요.',
  DB_SCHEMA_MISMATCH: '현재 코드에 필요한 DB 마이그레이션이 적용됐는지 확인하세요.',
  object_storage_unavailable: '파일 저장소 연결과 저장 공간·권한을 확인하세요.',
  response_validation_error: '백엔드 반환 타입·응답 모델과 실제 응답 구조를 확인하세요.',
  internal_server_error: '요청 ID로 백엔드 로그를 찾아 원인을 확인하세요.',
  invalid_response: '백엔드 API 주소·프록시 설정과 응답 형식을 확인하세요.',
  stream_error: '답변 생성이나 저장이 실패했습니다. 서비스 상태를 확인한 뒤 다시 요청하세요.',
  stream_interrupted: '답변이 완료되기 전에 연결이 끊겼습니다. 저장 여부를 확인한 뒤 다시 요청하세요.',
  client_error: '화면을 새로고침하고 같은 동작에서 반복되는지 확인하세요.',
  storage_unavailable: '브라우저 저장 공간 또는 사이트 저장 권한을 확인하세요. 새로고침하면 로그인·선택 상태가 사라질 수 있습니다.',
  file_validation: 'PDF·PPTX·DOCX 형식의 비어 있지 않은 파일을 선택하세요. 파일당 최대 25MB입니다.',
  validation_error: '입력 조건을 확인하고 잘못된 항목을 수정해주세요.',
  http_403: '현재 계정이 이 자료를 사용할 권한이 있는지 확인해주세요.',
  http_404: '자료가 삭제됐거나 API 경로가 변경됐는지 확인해주세요.',
  http_413: '파일을 나누거나 압축해 업로드 제한 이하로 줄여주세요.',
  http_415: 'PDF·PPTX·DOCX 파일을 선택해주세요.',
  http_502: '백엔드와 LLM 서비스 실행 상태 및 프록시 연결을 확인하세요.',
  http_503: '서비스 상태 확인 버튼에서 DB·LLM 연결을 확인하세요.',
  http_504: 'AI 응답 또는 서버 처리가 지연되고 있습니다. 서버 로그에서 진행 상태를 확인하세요.',
}
const FIELD_LABELS = { username: '아이디', password: '비밀번호', name: '이름', description: '설명', age: '나이', gender: '성별', file: '파일', message: '메시지', document_ids: '문서 목록', persona_ids: '질문자 목록', presentation_document_ids: '발표 자료', question_count_per_persona: '질문 개수' }

export function safeText(value, limit = 600) {
  return String(value ?? '').replace(/Bearer\s+\S+/gi, 'Bearer [숨김]')
    .replace(/\beyJ[\w-]+\.[\w-]+\.[\w-]+/g, '[토큰 숨김]')
    .replace(/(\w+:\/\/)[^\s/@]+:[^\s/@]+@/g, '$1[인증 정보 숨김]@')
    .replace(/((?:password|access_token|authorization|secret|api_key)\s*[=:]\s*)[^\s,;]+/gi, '$1[숨김]')
    .slice(0, limit)
}

export function safePath(value) {
  try { return new URL(value, 'http://local').pathname } catch { return '/' }
}

export function fieldErrors(items) {
  if (!Array.isArray(items)) return []
  return items.filter((item) => item && typeof item === 'object').slice(0, 20).map((item) => {
    const loc = Array.isArray(item.loc) ? item.loc.filter((part) => !['body', 'query', 'path'].includes(part)).join('.') : item.field || ''
    return { field: safeText(loc, 150), label: FIELD_LABELS[loc] || safeText(loc, 150), message: safeText(item.message || item.msg || '입력값을 확인해주세요.'), type: safeText(item.type || '', 100) }
  })
}

export class AppError extends Error {
  constructor(message, { code = 'client_error', status = null, path = '', method = '', requestId = '', fields = [], hint, retryAfter = null, authenticated = false, errorType = '' } = {}) {
    super(safeText(message || STATUS_MESSAGES[status] || '예상하지 못한 오류가 발생했습니다.'))
    this.name = 'AppError'
    Object.assign(this, { code: safeText(code, 100), status, path: path ? safePath(path) : '', method, requestId: safeText(requestId, 100), fields: fieldErrors(fields), hint: safeText(hint || GUIDANCE[code] || (status === 429 ? '표시된 대기 시간 후 다시 시도해주세요.' : '입력 내용과 서비스 상태를 확인해주세요.')), retryAfter, authenticated, errorType: safeText(errorType, 100) })
  }
}

export function fromPayload(payload, context = {}) {
  const detail = payload?.error || payload?.detail || payload
  const status = context.status
  let code = detail?.code || context.code || `http_${status || 'unknown'}`
  if (status === 401) code = context.path?.endsWith('/auth/login') ? 'invalid_credentials' : 'session_expired'
  if (status === 409 && context.path?.endsWith('/auth/signup')) code = 'username_taken'
  const fields = Array.isArray(detail) ? detail : detail?.fields || detail?.details || Object.entries(detail?.contract?.missing || {}).map(([field, columns]) => ({ field, message: `누락 항목: ${Array.isArray(columns) ? columns.join(', ') : '스키마 확인 필요'}` }))
  const message = typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : null
  return new AppError(message || STATUS_MESSAGES[status], { ...context, code, fields, requestId: detail?.request_id || context.requestId, hint: GUIDANCE[code], errorType: detail?.error_type })
}

export function normalizeError(error, context = {}) {
  if (error instanceof AppError) return error
  return new AppError('화면 처리 중 예상하지 못한 오류가 발생했습니다.', { ...context, code: 'client_error', errorType: error?.name || 'Error' })
}

let history = []
let sequence = 0
const listeners = new Set()
const reported = new WeakSet()
export const subscribeErrors = (listener) => { listeners.add(listener); return () => listeners.delete(listener) }
export const getErrors = () => history
export function reportError(error, context) {
  if (error?.name === 'AbortError') return null
  if (error && typeof error === 'object' && reported.has(error)) return error
  const normalized = normalizeError(error, context)
  if (error && typeof error === 'object') reported.add(error)
  reported.add(normalized)
  const record = { id: ++sequence, time: new Date().toISOString(), ...Object.fromEntries(['message', 'code', 'status', 'path', 'method', 'requestId', 'fields', 'hint', 'retryAfter', 'authenticated', 'errorType'].map((key) => [key, normalized[key]])) }
  history = [record, ...history].slice(0, 20)
  listeners.forEach((listener) => listener(record))
  return normalized
}
export function clearErrors() { history = []; listeners.forEach((listener) => listener(null)) }
export function reportLocalError(message, code = 'validation_error') {
  return reportError(new AppError(message, { code }))
}
export function diagnosticText(error) {
  return JSON.stringify({ time: error.time, code: error.code, message: error.message, status: error.status, method: error.method, path: error.path, requestId: error.requestId, fields: error.fields, hint: error.hint, retryAfter: error.retryAfter, errorType: error.errorType }, null, 2)
}
