import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createAgent, createSummary, deleteAgent, generateExpectedQuestions, getCurrentUser, listAgents, listDocuments, login, signup, streamChat, updateAgent, updateAgentDocuments, uploadDocument } from './api'
import { deleteDocument, getPracticeSession, listChats } from './api'
import WorkspaceLibrary, { CoverageNotice } from './WorkspaceLibrary'
import LoadingProgress from './LoadingProgress'
import { documentDeletePrompt, newConversation, readWorkspace, restorePracticeChats, shouldSubmitChatKey, validateFiles as checkFiles } from './workspace-utils.mjs'
import { reportLocalError, subscribeErrors } from './api-errors.mjs'

const ACCEPTED = [
  '.pdf',
  '.pptx',
  '.docx',
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
].join(',')
const sec = (ms = 0) => `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)}초`
const adaptPersona = (p) => ({ ...p, id: p.agent_id, documentIds: p.document_ids || [] })
const isCancelled = (error) => error?.name === 'AbortError'
const textLength = (doc) => doc.text_length ?? doc.full_text?.length ?? 0
let storageWarningShown = false
function storageWarning() {
  if (storageWarningShown) return
  storageWarningShown = true
  queueMicrotask(() => reportLocalError('브라우저에 로그인·작업 상태를 저장할 수 없습니다.', 'storage_unavailable'))
}
function stored(key) { try { return localStorage.getItem(key) } catch { storageWarning(); return null } }
function remember(key, value) { try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value) } catch { storageWarning() } }
function validateFiles(files) {
  const result = checkFiles(files)
  if (result.errors.length) reportLocalError(result.errors.join('\n'), 'file_validation')
  return result
}

function useRequestScope() {
  const scope = useMemo(() => {
    const requests = new Set()
    return {
      abort: () => requests.forEach((controller) => controller.abort()),
      run: async (task) => {
        const controller = new AbortController()
        requests.add(controller)
        try { return await task(controller.signal) } finally { requests.delete(controller) }
      },
    }
  }, [])
  useEffect(() => () => scope.abort(), [scope])
  return scope
}

function SourceEvidence({ sources = [] }) {
  if (!sources.length) return null
  return <details className="source-evidence"><summary>참고 근거 {sources.length}개</summary><ul>{sources.map((source, index) => <li key={`${source.document_id}-${source.page}-${index}`}><strong>{source.filename || '참고자료'}{source.page ? ` · ${source.page}쪽/슬라이드` : ''}</strong>{source.excerpt && <blockquote>{source.excerpt}</blockquote>}</li>)}</ul></details>
}

function ParseStatus({ doc }) {
  return <small className={`parse-status ${textLength(doc) ? 'ready' : 'unparsed'}`}>{textLength(doc) ? `텍스트 추출 완료 · ${textLength(doc).toLocaleString()}자` : '파일 보관 완료 · 추출된 텍스트 없음'}</small>
}

function Spinner({ label = '처리 중' }) {
  return <span className="loading-status" role="status" aria-live="polite"><span className="loading-spinner" aria-hidden="true" />{label}</span>
}

function Auth({ onLogin }) {
  const requests = useRequestScope()
  const [mode, setMode] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  async function submit(e) {
    e.preventDefault(); if (busy) return; setBusy(true); setNotice('')
    try {
      await requests.run(async (signal) => {
        if (mode === 'signup') {
          await signup({ username: username.trim(), password }, signal)
          if (!signal.aborted) { setMode('login'); setPassword(''); setNotice('회원가입 완료. 로그인해주세요.') }
          return
        }
        const data = await login({ username: username.trim(), password }, signal)
        if (!signal.aborted) onLogin(data.access_token)
      })
    } catch (err) { if (!isCancelled(err)) setNotice(err.message) } finally { setBusy(false) }
  }
  return <main className="auth-shell"><form className="auth-card" onSubmit={submit}>
    <div className="brand-mark">Q</div><h1>발표 예상 질문 연습</h1><p>발표 자료와 질문자의 관점을 연결해 실전 질문을 준비하세요.</p>
    <label>아이디<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" minLength={3} maxLength={32} pattern="[A-Za-z0-9_]+" title="영문, 숫자, 밑줄 3~32자" disabled={busy} required /></label>
    <label>비밀번호<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} minLength={8} maxLength={128} disabled={busy} required /></label>
    {notice && <p className="form-notice" role="status">{notice}</p>}
    <button className="primary-btn" disabled={busy}>{busy ? <Spinner label="확인 중" /> : mode === 'login' ? '로그인' : '회원가입'}</button>
    {busy && <LoadingProgress label={mode === 'login' ? '로그인 확인 중' : '계정 생성 중'} expected="보통 1~10초" slowAfterMs={15000} />}
    <button type="button" className="text-btn" disabled={busy} onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); setNotice('') }}>{mode === 'login' ? '계정 만들기' : '로그인으로'}</button>
  </form></main>
}

function Uploader({ documents, busyFiles, onFiles, onRemove, onCancel }) {
  const input = useRef(null)
  const [drag, setDrag] = useState(false)
  return <section className="source-block">
    <Heading title="1. 검토받을 발표 자료" text="PPT, 대본, 기획서와 부록을 추가합니다. 질문 생성에는 최대 20개를 선택하세요." count={`${documents.length}개`} />
    <button type="button" className={`drop-zone ${drag ? 'dragging' : ''}`} onClick={() => input.current?.click()} onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles([...e.dataTransfer.files]) }}>
      <b>＋</b><strong>여러 파일을 끌어놓거나 선택</strong><small>PDF · PPTX · DOCX, 파일당 최대 25MB</small>
    </button>
    <input ref={input} hidden multiple type="file" accept={ACCEPTED} onChange={(e) => { onFiles([...e.target.files]); e.target.value = '' }} />
    <div className="compact-files">{documents.map((d) => <div className="compact-file" key={d.document_id}><div><span title={d.filename}>📄 {d.filename}</span><ParseStatus doc={d} /></div><button type="button" className="text-btn" aria-label={`${d.filename} 발표 자료에서 제외`} onClick={() => onRemove(d.document_id)}>제외</button></div>)}{busyFiles.map((f) => <div className="compact-file upload-progress-card" key={f.id}><LoadingProgress compact label={`${f.name} 업로드·분석 중`} expected="문서 크기에 따라 보통 10초~5분" slowAfterMs={300000} /></div>)}</div>
    {busyFiles.length > 0 && <button type="button" className="text-btn" onClick={onCancel}>남은 업로드 취소</button>}
  </section>
}

function Heading({ title, text, count }) {
  return <div className="section-heading"><div><h3>{title}</h3><p>{text}</p></div>{count && <span className="count-pill">{count}</span>}</div>
}

function PersonaCreator({ token, onCreated, onDocuments, onDocumentRemoved }) {
  const requests = useRequestScope()
  const uploadControllers = useRef(new Map())
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [gender, setGender] = useState('unspecified')
  const [age, setAge] = useState('')
  const [files, setFiles] = useState([])
  const [pendingFiles, setPendingFiles] = useState([])
  const [busy, setBusy] = useState(false)
  const [stage, setStage] = useState('')
  const [error, setError] = useState('')
  useEffect(() => () => uploadControllers.current.forEach((controller) => controller.abort()), [])
  async function attachFiles(selectedFiles) {
    if (busy || pendingFiles.length) return
    setError('')
    const { accepted, errors } = validateFiles(selectedFiles)
    if (errors.length) setError(errors.join('\n'))
    const pending = accepted.map((file, index) => ({ id: `${Date.now()}-${index}-${Math.random()}`, name: file.name, file, status: '대기 중' }))
    for (const item of pending) uploadControllers.current.set(item.id, new AbortController())
    setPendingFiles(pending)
    for (const item of pending) {
      const controller = uploadControllers.current.get(item.id)
      if (!controller || controller.signal.aborted) continue
      setPendingFiles((items) => items.map((entry) => entry.id === item.id ? { ...entry, status: '업로드·분석 중' } : entry))
      try {
        const doc = await uploadDocument(item.file, token, controller.signal)
        if (controller.signal.aborted) {
          try { await deleteDocument(doc.document_id, token) } catch { /* best-effort cleanup after cancellation */ }
        } else {
          setFiles((old) => [...old.filter((entry) => entry.document_id !== doc.document_id), doc])
          onDocuments([doc])
        }
      } catch (err) {
        if (!isCancelled(err)) setError((current) => [current, `${item.name}: ${err.message}`].filter(Boolean).join('\n'))
      } finally {
        uploadControllers.current.delete(item.id)
        setPendingFiles((items) => items.filter((entry) => entry.id !== item.id))
      }
    }
  }
  function cancelPendingFile(id) {
    uploadControllers.current.get(id)?.abort()
    uploadControllers.current.delete(id)
    setPendingFiles((items) => items.filter((item) => item.id !== id))
  }
  async function submit(e) {
    e.preventDefault(); if (busy) return; setBusy(true); setError('')
    try {
      setStage('페르소나 준비 중')
      await requests.run(async (signal) => {
        const result = await createAgent({ name: name.trim(), description: description.trim(), gender, age: age ? Number(age) : null, documentIds: files.map((d) => d.document_id) }, token, signal)
        if (!signal.aborted) { onCreated(adaptPersona(result), files); setName(''); setDescription(''); setGender('unspecified'); setAge(''); setFiles([]); setOpen(false) }
      })
    } catch (err) { if (!isCancelled(err)) setError(err.message) } finally { setBusy(false); setStage('') }
  }
  async function removeSource(file) {
    if (busy) return
    setBusy(true); setStage(`${file.filename} 삭제 중`); setError('')
    try {
      await requests.run(async (signal) => {
        await deleteDocument(file.document_id, token, signal)
        if (!signal.aborted) {
          setFiles((items) => items.filter((item) => item.document_id !== file.document_id))
          onDocumentRemoved(file.document_id)
        }
      })
    } catch (err) { if (!isCancelled(err)) setError(`${file.filename} 삭제 실패: ${err.message}`) } finally { setBusy(false); setStage('') }
  }
  if (!open) return <button className="secondary-btn" onClick={() => setOpen(true)}>＋ 질문자 페르소나 만들기</button>
  return <form className="persona-form" onSubmit={submit}>
    <Heading title="새 질문자" text="교수, 투자자, 심사위원의 역할과 질문 성향을 설정합니다." />
    <label>이름<input value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 기술 심사위원" required /></label>
    <label>역할과 질문 성향<textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="기술 근거와 구현 가능성을 중점적으로 질문합니다." required /></label>
    <div className="demographic-fields">
      <label>성별<select value={gender} onChange={(e) => setGender(e.target.value)}><option value="unspecified">선택 안 함</option><option value="female">여성</option><option value="male">남성</option><option value="other">기타</option></select></label>
      <label>나이<input type="number" min="1" max="120" value={age} onChange={(e) => setAge(e.target.value)} placeholder="예: 45" /></label>
    </div>
    <label className="file-button">PDF·PPTX·DOCX 참고자료 추가<input className="visually-hidden" multiple disabled={busy || pendingFiles.length > 0} type="file" accept={ACCEPTED} onChange={(e) => { attachFiles([...e.target.files]); e.target.value = '' }} /></label>
    <div className="pending-persona-sources"><strong>선택한 참고자료 {files.length}개</strong>{files.length ? <div className="file-chip-row">{files.map((f) => <span className="file-chip" key={f.document_id}><span title={f.filename}>📎 {f.filename}</span><ParseStatus doc={f} /><button type="button" className="remove-source" disabled={busy} aria-label={`${f.filename} 소스 삭제`} onClick={() => removeSource(f)}>삭제</button></span>)}</div> : <p>첨부된 참고자료가 없습니다.</p>}{pendingFiles.length > 0 && <div className="pending-upload-list" aria-label="처리 중인 참고자료">{pendingFiles.map((file) => <div className="pending-upload" key={file.id}><LoadingProgress compact label={`${file.name} · ${file.status}`} expected="문서 크기에 따라 보통 10초~5분" slowAfterMs={300000} /><button type="button" className="remove-source" aria-label={`${file.name} 업로드 취소`} onClick={() => cancelPendingFile(file.id)}>취소</button></div>)}</div>}</div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {busy && <LoadingProgress label={stage} expected={stage.includes('삭제') ? '보통 1~10초' : '보통 1~30초'} slowAfterMs={60000} />}
    <div className="button-row"><button type="button" className="text-btn" disabled={busy} onClick={() => setOpen(false)}>닫기</button><button className="primary-btn" disabled={busy || pendingFiles.length > 0 || !name.trim() || !description.trim()}>{busy ? <Spinner label={stage} /> : pendingFiles.length > 0 ? '자료 처리 완료 후 생성' : '페르소나 생성'}</button></div>
  </form>
}

function PersonaEditor({ persona, documents, token, onSaved, onChanged, onCancel, onDocuments }) {
  const requests = useRequestScope()
  const [name, setName] = useState(persona.name)
  const [description, setDescription] = useState(persona.description || '')
  const [gender, setGender] = useState(persona.gender || 'unspecified')
  const [age, setAge] = useState(persona.age || '')
  const [documentIds, setDocumentIds] = useState(persona.documentIds)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const linked = documentIds.map((id) => documents.find((doc) => doc.document_id === id)).filter(Boolean)
  async function attachFiles(selectedFiles) {
    if (busy) return
    setBusy(true); setError('')
    const { accepted, errors } = validateFiles(selectedFiles)
    try {
      await requests.run(async (signal) => {
        let ids = [...documentIds]
        for (const file of accepted) {
          if (signal.aborted) break
          try {
            const doc = await uploadDocument(file, token, signal)
            if (signal.aborted) break
            onDocuments([doc])
            const updated = adaptPersona(await updateAgentDocuments(persona.id, [...new Set([...ids, doc.document_id])], token, signal))
            if (!signal.aborted) { ids = updated.documentIds; setDocumentIds(ids); onChanged(updated) }
          } catch (err) { if (isCancelled(err)) break; errors.push(`${file.name}: ${err.message}`) }
        }
        if (!signal.aborted) setError(errors.join('\n'))
      })
    } finally { setBusy(false) }
  }
  async function removeDocument(documentId) {
    if (busy) return; setBusy(true); setError('')
    try {
      await requests.run(async (signal) => {
        const updated = adaptPersona(await updateAgentDocuments(persona.id, documentIds.filter((id) => id !== documentId), token, signal))
        if (!signal.aborted) { setDocumentIds(updated.documentIds); onChanged(updated) }
      })
    } catch (err) { if (!isCancelled(err)) setError(err.message) } finally { setBusy(false) }
  }
  async function submit(e) {
    e.preventDefault(); if (busy) return; setBusy(true); setError('')
    try {
      await requests.run(async (signal) => {
        const saved = adaptPersona(await updateAgent(persona.id, { name: name.trim(), description: description.trim(), gender, age: age ? Number(age) : null, documentIds }, token, signal))
        if (!signal.aborted) onSaved(saved)
      })
    } catch (err) { if (!isCancelled(err)) setError(err.message) } finally { setBusy(false) }
  }
  return <form className="persona-form persona-edit-form" onSubmit={submit}>
    <Heading title={`${persona.name} 수정`} text="참고자료 연결 변경은 즉시 저장됩니다. 이름과 역할은 수정 저장을 눌러주세요." />
    <label>이름<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
    <label>역할과 질문 성향<textarea value={description} onChange={(e) => setDescription(e.target.value)} required /></label>
    <div className="demographic-fields"><label>성별<select value={gender} onChange={(e) => setGender(e.target.value)}><option value="unspecified">선택 안 함</option><option value="female">여성</option><option value="male">남성</option><option value="other">기타</option></select></label><label>나이<input type="number" min="1" max="120" value={age} onChange={(e) => setAge(e.target.value)} /></label></div>
    <div><strong>현재 첨부자료 {linked.length}개</strong><div className="persona-source-list">{linked.length ? linked.map((doc) => <div key={doc.document_id}><span title={doc.filename}>📎 {doc.filename}<ParseStatus doc={doc} /></span><button type="button" disabled={busy} aria-label={`${doc.filename} 질문자 자료 연결 해제`} onClick={() => removeDocument(doc.document_id)}>연결 해제</button></div>) : <p>첨부된 자료가 없습니다.</p>}</div></div>
    <label className="file-button">＋ 새 자료 즉시 첨부<input className="visually-hidden" multiple disabled={busy} type="file" accept={ACCEPTED} onChange={(e) => { attachFiles([...e.target.files]); e.target.value = '' }} /></label>
    {error && <p className="form-error" role="alert">{error}</p>}
    {busy && <LoadingProgress label="질문자와 자료 저장 중" expected="자료 첨부 시 보통 10초~5분, 일반 수정은 1~10초" slowAfterMs={300000} />}
    <div className="button-row"><button type="button" className="text-btn" disabled={busy} onClick={onCancel}>닫기</button><button className="primary-btn" disabled={busy || !name.trim() || !description.trim()}>{busy ? <Spinner label="수정·자료 저장 중" /> : '수정 저장'}</button></div>
  </form>
}

function ChatPanel({ result, token, documentIds, chat, update }) {
  const box = useRef(null)
  const inFlight = useRef(new Map())
  const nearBottom = useRef(true)
  const [showJump, setShowJump] = useState(false)
  const [, tick] = useState(0)
  const activeId = chat?.activeQuestionId || null
  const conversation = activeId ? chat?.conversations?.[activeId] : null
  const mutateConversation = (questionId, fn) => update((state) => !state?.conversations?.[questionId] ? state : ({
    ...state,
    conversations: {
      ...state.conversations,
      [questionId]: fn(state.conversations[questionId]),
    },
  }))
  useEffect(() => () => inFlight.current.forEach((controller) => controller.abort()), [])
  useEffect(() => () => inFlight.current.forEach((controller) => controller.abort()), [result])
  useEffect(() => { if (!conversation?.sending) return; const id = setInterval(() => tick((n) => n + 1), 250); return () => clearInterval(id) }, [conversation?.sending])
  useEffect(() => { nearBottom.current = true; setShowJump(false); if (box.current) box.current.scrollTop = box.current.scrollHeight }, [activeId])
  useEffect(() => {
    if ((nearBottom.current || conversation?.forceScroll) && box.current) {
      box.current.scrollTop = box.current.scrollHeight
      nearBottom.current = true
      setShowJump(false)
    }
    if (conversation?.forceScroll && activeId) mutateConversation(activeId, (state) => ({ ...state, forceScroll: false }))
  }, [conversation?.messages, conversation?.forceScroll, activeId])
  const elapsed = conversation?.sending ? performance.now() - conversation.startedAt : conversation?.lastTiming?.total_ms || 0
  function choose(q) {
    update((state) => ({
      ...state,
      activeQuestionId: q.question_id,
      conversations: {
        ...state.conversations,
        [q.question_id]: state.conversations[q.question_id] || newConversation(q),
      },
    }))
  }
  async function send(e) {
    e.preventDefault(); const questionId = activeId; const value = conversation?.input.trim(); if (!value || conversation.sending || !questionId || inFlight.current.has(questionId)) return
    const controller = new AbortController()
    inFlight.current.set(questionId, controller)
    const aid = `a-${Date.now()}`
    const uid = `u-${Date.now()}`
    mutateConversation(questionId, (state) => ({ ...state, input: '', sending: true, startedAt: performance.now(), error: '', forceScroll: true, messages: [...state.messages, { id: uid, role: 'user', text: value }, { id: aid, role: 'persona', text: '', pending: true }] }))
    try {
      const item = await streamChat({ agentId: result.persona_id, conversationId: conversation.conversationId, message: `예상 질문: ${conversation.question.question}\n발표자의 답변: ${value}\n답변을 평가하고 후속 질문을 해주세요.`, documentIds, responseDetail: 'detailed', token, signal: controller.signal, onToken: (part) => { if (!controller.signal.aborted) mutateConversation(questionId, (state) => ({ ...state, messages: state.messages.map((m) => m.id === aid ? { ...m, text: m.text + part } : m) })) } })
      if (!controller.signal.aborted) mutateConversation(questionId, (state) => ({ ...state, sending: false, lastTiming: item.timing, messages: state.messages.map((m) => m.id === aid ? { ...m, text: item.answer, pending: false, timing: item.timing, sources: item.sources, grounding: item.grounding } : m) }))
    } catch (err) {
      mutateConversation(questionId, (state) => ({ ...state, sending: false, input: state.input || value, error: isCancelled(err) ? '답변 요청을 취소했습니다. 입력한 내용은 보관했습니다.' : err.message, messages: state.messages.filter((m) => m.id !== aid && m.id !== uid) }))
    } finally { inFlight.current.delete(questionId) }
  }
  return <article className="chat-panel">
    <header className="chat-persona-header"><img src={result.avatar_data_url} alt={`${result.persona_name} AI 생성 아바타`} /><div><h3>{result.persona_name}</h3><p>{result.persona_role} · AI 생성 아바타</p></div>{conversation?.sending && <LoadingProgress compact elapsedMs={elapsed} label="답변 생성 중" expected="첫 응답은 보통 5초~2분" slowAfterMs={120000} />}</header>
    <CoverageNotice coverage={result.coverage} />{result.warnings?.map((w) => <p key={w} className="grounding-note">{w}</p>)}{result.assessment && <p className="grounding-note">{result.assessment.basis}</p>}<p>요청 상한 {result.requested_count ?? 5}개 · 생성 {result.generated_count ?? result.questions.length}개</p>
    <div className="question-strip" aria-label={`${result.persona_name}의 예상 질문`}>{result.questions.map((q, i) => <button type="button" aria-pressed={activeId === q.question_id} className={activeId === q.question_id ? 'active' : ''} key={q.question_id} onClick={() => choose(q)}><b>Q{i + 1}</b>{q.origin === 'template' && <small>보충 질문 · </small>}{q.question}{chat?.conversations?.[q.question_id]?.sending && <span className="loading-spinner" aria-label="답변 생성 중" />}</button>)}</div>
    <div className="messages" aria-label={`${result.persona_name} 질문별 대화 기록`} tabIndex={0} ref={box} onScroll={(e) => { const n = e.currentTarget; nearBottom.current = n.scrollHeight - n.scrollTop - n.clientHeight < 80; setShowJump(!nearBottom.current) }}>
      {!conversation && <p className="empty-state">예상 질문을 선택하세요.</p>}
      {(conversation?.messages || []).map((m) => <div className={`message ${m.role}`} key={m.id}><div>{m.text || (m.pending && <Spinner label="첫 응답 대기 중" />)}</div><SourceEvidence sources={m.sources} />{m.pending && m.text && <small>생성 중 · 근거 검증 전</small>}{m.grounding && !m.grounding.checked && <p className="grounding-note">근거 검증을 완료하지 못했습니다.</p>}{m.sources?.length > 0 && !m.id?.startsWith('q-') && !/\[근거\s+\d+\]/.test(m.text) && <small>참고자료이며 답변의 직접 인용은 확인되지 않았습니다.</small>}{m.grounding?.checked && m.grounding.unsupported?.length > 0 && <p className="grounding-note">일부 주장의 문서 근거가 부족합니다. 참고자료와 함께 확인해주세요.</p>}{m.timing && <details className="timing"><summary>첫 응답 {sec(m.timing.first_content_latency_ms)} · 전체 {sec(m.timing.total_ms)} · {m.timing.output_lines}줄</summary><p>자료 {sec(m.timing.context_ms)} · 생성 {sec(m.timing.generation_ms)} · 저장 {sec(m.timing.save_ms)}</p></details>}</div>)}
      {showJump && <button className="jump-bottom" onClick={() => activeId && mutateConversation(activeId, (state) => ({ ...state, forceScroll: true }))}>새 메시지 보기 ↓</button>}
    </div>
    <form className="chat-composer" onSubmit={send}><textarea value={conversation?.input || ''} aria-label={`${result.persona_name}에게 보낼 답변`} maxLength={Math.max(1, 4900 - (conversation?.question.question.length || 0))} onChange={(e) => activeId && mutateConversation(activeId, (state) => ({ ...state, input: e.target.value }))} onKeyDown={(e) => { if (!shouldSubmitChatKey({ key: e.key, shiftKey: e.shiftKey, isComposing: e.nativeEvent?.isComposing, keyCode: e.keyCode })) return; e.preventDefault(); if (conversation?.input?.trim()) e.currentTarget.form?.requestSubmit() }} placeholder={conversation ? '발표자의 답변을 입력하세요 (Shift+Enter 줄바꿈)' : '먼저 예상 질문을 선택하세요'} disabled={!conversation || conversation.sending} />{conversation?.sending ? <button type="button" className="send-btn" onClick={() => inFlight.current.get(activeId)?.abort()}>중지</button> : <button className="send-btn" disabled={!conversation || !conversation.input?.trim()}>전송</button>}</form>
    {conversation?.error && <p className="form-error" role="alert">{conversation.error}</p>}
  </article>
}

const SUMMARY_STYLES = [
  { value: 'brief', label: '간단히' },
  { value: 'detailed', label: '자세히' },
  { value: 'outline', label: '개요만' },
]

function DocumentSummaryPanel({ doc, token }) {
  const requests = useRequestScope()
  const [open, setOpen] = useState(false)
  const [style, setStyle] = useState('brief')
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function load(targetStyle, refresh = false) {
    setBusy(true); setError('')
    try { await requests.run(async (signal) => { const result = await createSummary(doc.document_id, { style: targetStyle, refresh }, token, signal); if (!signal.aborted) setData(result) }) } catch (err) { if (!isCancelled(err)) setError(err.message) } finally { setBusy(false) }
  }
  function toggle() {
    const next = !open
    setOpen(next)
    if (next && !data) load(style)
  }
  function changeStyle(nextStyle) {
    setStyle(nextStyle)
    load(nextStyle)
  }
  return <div className="summary-panel">
    <button type="button" className="text-btn" onClick={toggle}>{open ? '요약 접기 ▲' : '요약 보기 ▼'}</button>
    {open && <div className="summary-body">
      <div className="summary-style-row">
        {SUMMARY_STYLES.map((s) => <button key={s.value} type="button" className={style === s.value ? 'active' : ''} disabled={busy} onClick={() => changeStyle(s.value)}>{s.label}</button>)}
        <button type="button" disabled={busy} onClick={() => load(style, true)}>다시 생성</button>
      </div>
      {busy && <LoadingProgress label="자료 요약 생성 중" expected="문서 길이에 따라 보통 10초~5분" slowAfterMs={300000} />}
      {error && <p className="form-error">{error}</p>}
      {data && !busy && <>
        <CoverageNotice coverage={data.coverage} />{data.warnings?.map((warning) => <p className="grounding-note" key={warning}>{warning}</p>)}<p className="summary-text">{data.summary}</p>
        {data.key_topics?.length > 0 && <ul className="summary-topics">{data.key_topics.map((topic, i) => <li key={i}><strong>{topic.topic}</strong> — {topic.description}<SourceEvidence sources={topic.sources} /></li>)}</ul>}
        {data.outline?.length > 0 && <ol className="summary-outline">{data.outline.map((item, i) => <li key={i}>{item}</li>)}</ol>}
      </>}
    </div>}
  </div>
}

export default function App() {
  const [token, setToken] = useState(() => stored('authToken'))
  function changeToken(value) { remember('authToken', value); setToken(value) }
  useEffect(() => subscribeErrors((error) => {
    if (error?.status === 401 && error.authenticated) changeToken(null)
  }), [])
  return token ? <Workspace key={token} token={token} onLogout={() => changeToken(null)} /> : <Auth onLogin={changeToken} />
}

function Workspace({ token, onLogout }) {
  const requests = useRequestScope()
  const uploadRequests = useRequestScope()
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(token))
  const [documents, setDocuments] = useState([])
  const [projectIds, setProjectIds] = useState([])
  const [personas, setPersonas] = useState([])
  const [selected, setSelected] = useState([])
  const [uploads, setUploads] = useState([])
  const [results, setResults] = useState([])
  const [chats, setChats] = useState({})
  const [generating, setGenerating] = useState(false)
  const [questionCount, setQuestionCount] = useState(5)
  const [sessionRevision, setSessionRevision] = useState(0)
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [practiceDocumentIds, setPracticeDocumentIds] = useState([])
  const [deletingDocumentId, setDeletingDocumentId] = useState(null)
  const [deletingPersonaId, setDeletingPersonaId] = useState(null)
  function resumeSession(session, history, docs = documents, agents = personas) {
    setSessionRevision((n) => n + 1)
    const availableIds = new Set(agents.map((p) => p.id || p.agent_id))
    const response = { ...session.response, results: session.response.results.filter((r) => availableIds.has(r.persona_id)) }
    const restored = { ...session, response }
    setResults(response.results); setChats(restorePracticeChats(restored, history))
    setActiveSessionId(session.session_id)
    setQuestionCount(session.request.question_count_per_persona)
    const ids = session.request.presentation_document_ids.filter((id) => docs.some((d) => d.document_id === id))
    setProjectIds(ids); setPracticeDocumentIds(ids)
    setSelected(session.request.persona_ids.filter((id) => availableIds.has(id)))
    setError(session.warnings.join(' '))
  }
  async function refreshResources() {
    const [docs, agents] = await Promise.all([listDocuments(token), listAgents(token)])
    setDocuments(docs); setPersonas(agents.map(adaptPersona))
    if (activeSessionId) {
      const [session, history] = await Promise.all([getPracticeSession(activeSessionId, token), listChats(token)])
      resumeSession(session, history, docs, agents)
    }
  }
  async function removeDocument(doc) {
    if (deletingDocumentId || !window.confirm(documentDeletePrompt(doc.filename))) return
    setDeletingDocumentId(doc.document_id); setError('')
    try {
      await deleteDocument(doc.document_id, token)
      setProjectIds((ids) => ids.filter((id) => id !== doc.document_id))
      setPracticeDocumentIds((ids) => ids.filter((id) => id !== doc.document_id))
      await refreshResources()
    } catch (err) { setError(`${doc.filename} 삭제 실패: ${err.message}`) }
    finally { setDeletingDocumentId(null) }
  }
  const [editingPersonaId, setEditingPersonaId] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!token) { setLoading(false); return }
    let alive = true; setLoading(true)
    Promise.all([getCurrentUser(token), listDocuments(token), listAgents(token)]).then(async ([u, docs, agents]) => {
      if (!alive) return
      setUser(u); setDocuments(docs); setPersonas(agents.map(adaptPersona))
      const saved = readWorkspace(stored(`presentationWorkspace:${u.user_id}`), docs, agents)
      setProjectIds(saved.projectIds)
      setSelected(saved.selected)
      const sessionId = stored(`activePractice:${u.user_id}`)
      if (sessionId) {
        try {
          const [session, history] = await Promise.all([getPracticeSession(sessionId, token), listChats(token)])
          if (alive) resumeSession(session, history, docs, agents)
        } catch (err) { if (alive) setError(err.message) }
      }
    }).catch((err) => { if (!alive) return; if (err.status === 401) onLogout(); else setError(err.message) }).finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [token])
  useEffect(() => { if (user) remember(`presentationWorkspace:${user.user_id}`, JSON.stringify({ projectIds, selected })) }, [user, projectIds, selected])
  useEffect(() => { if (user && activeSessionId) remember(`activePractice:${user.user_id}`, activeSessionId) }, [user, activeSessionId])
  const projectDocs = useMemo(() => documents.filter((d) => projectIds.includes(d.document_id)), [documents, projectIds])

  async function addFiles(files) {
    const { accepted, errors } = validateFiles(files)
    setError(errors.join('\n'))
    await uploadRequests.run(async (signal) => { for (const file of accepted) {
      if (signal.aborted) break
      const pending = { id: `${Date.now()}-${Math.random()}`, name: file.name }; setUploads((x) => [...x, pending])
      try { const doc = await uploadDocument(file, token, signal); if (signal.aborted) break; setDocuments((x) => [...x.filter((d) => d.document_id !== doc.document_id), doc]); setProjectIds((x) => [...new Set([...x, doc.document_id])]) } catch (err) { if (!isCancelled(err)) { errors.push(`${file.name}: ${err.message}`); setError(errors.join('\n')) } } finally { setUploads((x) => x.filter((p) => p.id !== pending.id)) }
    } })
  }
  function togglePersona(id) { setSelected((x) => x.includes(id) ? x.filter((v) => v !== id) : x.length < 4 ? [...x, id] : x) }
  async function removePersona(persona) {
    if (deletingPersonaId || !window.confirm(`${persona.name} 질문자를 삭제하시겠습니까? 휴지통으로 이동합니다.`)) return
    setDeletingPersonaId(persona.id); setError('')
    try {
      await deleteAgent(persona.id, token)
      setPersonas((items) => items.filter((item) => item.id !== persona.id))
      setSelected((items) => items.filter((id) => id !== persona.id))
      setResults((items) => items.filter((item) => item.persona_id !== persona.id))
      setEditingPersonaId((id) => id === persona.id ? null : id)
    } catch (err) { setError(`${persona.name} 삭제 실패: ${err.message}`) }
    finally { setDeletingPersonaId(null) }
  }
  async function makeQuestions() {
    if (generating) return
    setGenerating(true); setError('')
    try { await requests.run(async (signal) => { const data = await generateExpectedQuestions({ personaIds: selected, presentationDocumentIds: projectIds, questionCount }, token, signal); if (signal.aborted) return; setResults(data.results); setActiveSessionId(data.session_id); setPracticeDocumentIds(projectIds); setChats(Object.fromEntries(data.results.map((r) => [r.persona_id, { activeQuestionId: null, conversations: {} }]))) }) } catch (err) { if (!isCancelled(err)) setError(err.message) } finally { setGenerating(false) }
  }
  if (loading) return <main className="center-screen"><LoadingProgress label="작업공간 불러오는 중" expected="보통 1~15초" slowAfterMs={30000} /></main>
  return <div className="workspace-shell">
    <header className="topbar"><div><span className="brand-mark small">Q</span><strong>발표 질문 시뮬레이터</strong></div><div>{user?.username}<button className="text-btn" onClick={onLogout}>로그아웃</button></div></header>
    <main className="workspace-main">
      <section className="hero-copy"><span className="eyebrow">PRESENTATION WORKSPACE</span><h1>발표 자료를 기준으로<br />질문자들과 미리 대화하세요.</h1><p>발표 자료와 대본을 여러 개 넣고 최대 네 명의 질문자 관점을 동시에 준비합니다.</p></section>
      <div className="setup-grid">
        <Uploader documents={projectDocs} busyFiles={uploads} onFiles={addFiles} onRemove={(id) => setProjectIds((ids) => ids.filter((value) => value !== id))} onCancel={uploadRequests.abort} />
        <section className="source-block">
          <Heading title="2. 질문자 선택" text="질문자별 자료를 확인하고 수정할 수 있습니다." count={`${selected.length} / 4`} />
          <div className="persona-grid">{personas.map((p) => {
            const linked = p.documentIds.map((id) => documents.find((doc) => doc.document_id === id)).filter(Boolean)
            return <article className={`persona-entry ${selected.includes(p.id) ? 'selected' : ''}`} key={p.id}>
              <button type="button" className="persona-choice" disabled={!selected.includes(p.id) && selected.length === 4} onClick={() => togglePersona(p.id)}><span className="avatar-fallback">{p.name.slice(0, 2)}</span><span><strong>{p.name}</strong><small>{p.role} · {p.age ? `${p.age}세 · ` : ''}자료 {linked.length}개</small></span><b>{selected.includes(p.id) ? '✓' : '+'}</b></button>
              <div className="persona-inline-sources">{linked.length ? linked.map((doc) => <span key={doc.document_id}>📎 {doc.filename}</span>) : <small>첨부자료 없음</small>}</div>
              <div className="persona-actions"><button type="button" disabled={Boolean(deletingPersonaId)} onClick={() => setEditingPersonaId((id) => id === p.id ? null : p.id)}>수정</button><button type="button" className="danger-action" disabled={Boolean(deletingPersonaId)} onClick={() => removePersona(p)}>{deletingPersonaId === p.id ? '삭제 중…' : '삭제'}</button></div>
              {deletingPersonaId === p.id && <LoadingProgress compact label={`${p.name} 휴지통 이동 중`} expected="보통 1~10초" slowAfterMs={15000} />}
              {editingPersonaId === p.id && <PersonaEditor persona={p} documents={documents} token={token} onCancel={() => setEditingPersonaId(null)} onDocuments={(docs) => setDocuments((current) => [...current, ...docs.filter((doc) => !current.some((item) => item.document_id === doc.document_id))])} onChanged={(changed) => setPersonas((items) => items.map((item) => item.id === changed.id ? changed : item))} onSaved={(saved) => { setPersonas((items) => items.map((item) => item.id === saved.id ? saved : item)); setEditingPersonaId(null) }} />}
            </article>
          })}</div>
          <PersonaCreator token={token} onDocuments={(docs) => setDocuments((items) => [...items, ...docs.filter((doc) => !items.some((item) => item.document_id === doc.document_id))])} onDocumentRemoved={(id) => { setDocuments((items) => items.filter((item) => item.document_id !== id)); setProjectIds((ids) => ids.filter((item) => item !== id)) }} onCreated={(p) => setPersonas((x) => [...x, p])} />
        </section>
      </div>
      <section className="generate-bar"><div><strong>예상 질문 준비</strong><label> 질문자별 개수 <select value={questionCount} onChange={(e) => setQuestionCount(Number(e.target.value))}>{Array.from({ length: 10 }, (_, i) => <option key={i + 1}>{i + 1}</option>)}</select></label><p>발표 자료 {projectIds.length}/20개 · 질문자 {selected.length}명</p>{projectIds.length > 20 && <p role="alert">질문 생성에 사용할 발표 자료를 20개 이하로 줄여주세요.</p>}</div><button className="primary-btn" disabled={generating || !projectIds.length || projectIds.length > 20 || !selected.length || projectDocs.some((d) => !textLength(d))} onClick={makeQuestions}>{generating ? <Spinner label="질문 생성 중" /> : '예상 질문 생성'}</button>{generating && <div className="generate-progress"><LoadingProgress label={`질문자 ${selected.length}명 예상 질문 생성 중`} expected="로컬 모델 기준 질문자당 약 15초~2분, CPU 환경은 더 걸릴 수 있습니다." slowAfterMs={selected.length * 120000} /></div>}</section>
      {error && <p className="global-error">{error}</p>}
      {results.length > 0 && <section><div className="section-title"><span className="eyebrow">PRACTICE</span><h2>페르소나별 답변 연습</h2><p>질문을 고른 뒤 답변하세요. 각 채팅창은 독립적으로 동작합니다.</p></div><div className={`chat-grid panels-${results.length}`}>{results.map((r) => <ChatPanel key={`${activeSessionId}-${sessionRevision}-${r.persona_id}`} result={r} token={token} documentIds={practiceDocumentIds} chat={chats[r.persona_id]} update={(fn) => setChats((all) => ({ ...all, [r.persona_id]: fn(all[r.persona_id]) }))} />)}</div></section>}
      <WorkspaceLibrary token={token} documents={documents} personas={personas} onResume={resumeSession} onChanged={refreshResources} />
      <section className="materials-overview"><div className="section-title"><span className="eyebrow">SOURCE MAP</span><h2>자료 사용 위치</h2><p>발표·페르소나·예상 질문·채팅에 사용된 위치를 표시합니다.</p></div><div className="materials-table">{documents.map((d) => { const linked = personas.filter((p) => p.documentIds.includes(d.document_id)); const used = results.some((r) => r.questions.some((q) => q.sources?.some((s) => s.document_id === d.document_id))); const chatUsed = Object.values(chats).some((chat) => Object.values(chat.conversations || {}).some((conversation) => (conversation.messages || []).some((message) => !message.id?.startsWith('q-') && (message.sources || []).some((source) => source.document_id === d.document_id)))); return <div className="material-card" key={d.document_id}><div><strong>{d.filename}</strong><small>{d.document_type?.toUpperCase()} · {d.text_length || d.full_text?.length || 0}자</small></div><div className="usage-list">{projectIds.includes(d.document_id) && <em className="usage-badge user">사용자 발표 자료</em>}{linked.map((p) => <em className="usage-badge persona" key={p.id}>{p.name} 자료</em>)}{used && <em className="usage-badge question">예상 질문 사용</em>}{chatUsed && <em className="usage-badge chat">채팅 참고 후보</em>}{!projectIds.includes(d.document_id) && !linked.length && <em className="usage-badge unused">미사용</em>}</div><div className="material-actions"><button type="button" className="text-btn" disabled={deletingDocumentId === d.document_id} onClick={() => setProjectIds((x) => x.includes(d.document_id) ? x.filter((id) => id !== d.document_id) : [...x, d.document_id])}>{projectIds.includes(d.document_id) ? '발표에서 제외' : '발표에 사용'}</button><button type="button" className="danger-action source-delete" disabled={Boolean(deletingDocumentId)} aria-label={`${d.filename} 소스 삭제`} onClick={() => removeDocument(d)}>{deletingDocumentId === d.document_id ? '삭제 중…' : '소스 삭제'}</button></div>{deletingDocumentId === d.document_id && <div className="material-delete-progress"><LoadingProgress compact label={`${d.filename} 원본·DB 삭제 중`} expected="보통 1~15초" slowAfterMs={30000} /></div>}{d.warnings?.map((w) => <p key={w} className="grounding-note">{w}</p>)}<DocumentSummaryPanel doc={d} token={token} /></div> })}</div></section>
    </main>
  </div>
}
