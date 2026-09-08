import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createAgent, createSummary, deleteAgent, generateExpectedQuestions, getCurrentUser, listAgents, listDocuments, login, signup, streamChat, updateAgent, updateAgentDocuments, uploadDocument } from './api'

const ACCEPTED = [
  '.pdf',
  '.pptx',
  '.docx',
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
].join(',')
const SUPPORTED_EXTENSIONS = new Set(['pdf', 'pptx', 'docx'])
const supportedFiles = (files) => files.filter((file) => SUPPORTED_EXTENSIONS.has(file.name.split('.').pop()?.toLowerCase()))
const sec = (ms = 0) => `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)}초`
const adaptPersona = (p) => ({ ...p, id: p.agent_id, documentIds: p.document_ids || [] })

function Spinner({ label = '처리 중' }) {
  return <span className="loading-status" role="status" aria-live="polite"><span className="loading-spinner" aria-hidden="true" />{label}</span>
}

function Auth({ onLogin }) {
  const [mode, setMode] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  async function submit(e) {
    e.preventDefault(); setBusy(true); setNotice('')
    try {
      if (mode === 'signup') {
        await signup({ username, password }); setMode('login'); setNotice('회원가입 완료. 로그인해주세요.'); return
      }
      const data = await login({ username, password }); localStorage.setItem('authToken', data.access_token); onLogin(data.access_token)
    } catch (err) { setNotice(err.message) } finally { setBusy(false) }
  }
  return <main className="auth-shell"><form className="auth-card" onSubmit={submit}>
    <div className="brand-mark">Q</div><h1>발표 예상 질문 연습</h1><p>발표 자료와 질문자의 관점을 연결해 실전 질문을 준비하세요.</p>
    <label>아이디<input value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} required /></label>
    <label>비밀번호<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required /></label>
    {notice && <p className="form-notice">{notice}</p>}
    <button className="primary-btn" disabled={busy}>{busy ? <Spinner label="확인 중" /> : mode === 'login' ? '로그인' : '회원가입'}</button>
    <button type="button" className="text-btn" onClick={() => setMode(mode === 'login' ? 'signup' : 'login')}>{mode === 'login' ? '계정 만들기' : '로그인으로'}</button>
  </form></main>
}

function Uploader({ documents, busyFiles, onFiles }) {
  const input = useRef(null)
  const [drag, setDrag] = useState(false)
  return <section className="source-block">
    <Heading title="1. 검토받을 발표 자료" text="PPT, 대본, 기획서와 부록을 제한 없이 추가합니다." count={`${documents.length}개`} />
    <button type="button" className={`drop-zone ${drag ? 'dragging' : ''}`} onClick={() => input.current?.click()} onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(supportedFiles([...e.dataTransfer.files])) }}>
      <b>＋</b><strong>여러 파일을 끌어놓거나 선택</strong><small>PDF · PPTX · DOCX, 파일당 최대 25MB</small>
    </button>
    <input ref={input} hidden multiple type="file" accept={ACCEPTED} onChange={(e) => { onFiles(supportedFiles([...e.target.files])); e.target.value = '' }} />
    <div className="compact-files">{documents.map((d) => <div className="compact-file" key={d.document_id}>📄 <span>{d.filename}</span><em>사용자 발표 자료</em></div>)}{busyFiles.map((f) => <div className="compact-file" key={f.id}><Spinner label={`${f.name} 업로드·분석 중`} /></div>)}</div>
  </section>
}

function Heading({ title, text, count }) {
  return <div className="section-heading"><div><h3>{title}</h3><p>{text}</p></div>{count && <span className="count-pill">{count}</span>}</div>
}

function PersonaCreator({ token, onCreated }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [gender, setGender] = useState('unspecified')
  const [age, setAge] = useState('')
  const [files, setFiles] = useState([])
  const [busy, setBusy] = useState(false)
  const [stage, setStage] = useState('')
  const [error, setError] = useState('')
  async function attachFiles(selectedFiles) {
    setBusy(true); setError('')
    try {
      const uploaded = []
      for (const file of supportedFiles(selectedFiles)) { setStage(`${file.name} 업로드 중`); uploaded.push(await uploadDocument(file, token)) }
      setFiles((old) => [...old, ...uploaded])
    } catch (err) { setError(err.message) } finally { setBusy(false); setStage('') }
  }
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      setStage('페르소나 준비 중')
      const result = await createAgent({ name, description, gender, age: age ? Number(age) : null, documentIds: files.map((d) => d.document_id) }, token)
      onCreated(adaptPersona(result), files); setName(''); setDescription(''); setGender('unspecified'); setAge(''); setFiles([]); setOpen(false)
    } catch (err) { setError(err.message) } finally { setBusy(false); setStage('') }
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
    <label className="file-button">PDF·PPTX·DOCX 참고자료 추가<input hidden multiple disabled={busy} type="file" accept={ACCEPTED} onChange={(e) => { attachFiles([...e.target.files]); e.target.value = '' }} /></label>
    <div className="file-chip-row">{files.map((f, i) => <span className="file-chip" key={f.document_id}>{f.filename}<button type="button" onClick={() => setFiles((old) => old.filter((_, n) => n !== i))}>×</button></span>)}</div>
    {error && <p className="form-error">{error}</p>}
    <div className="button-row"><button type="button" className="text-btn" onClick={() => setOpen(false)}>취소</button><button className="primary-btn" disabled={busy}>{busy ? <Spinner label={stage} /> : '페르소나 생성'}</button></div>
  </form>
}

function PersonaEditor({ persona, documents, token, onSaved, onChanged, onCancel, onDocuments }) {
  const [name, setName] = useState(persona.name)
  const [description, setDescription] = useState(persona.description || '')
  const [gender, setGender] = useState(persona.gender || 'unspecified')
  const [age, setAge] = useState(persona.age || '')
  const [documentIds, setDocumentIds] = useState(persona.documentIds)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const linked = documentIds.map((id) => documents.find((doc) => doc.document_id === id)).filter(Boolean)
  async function attachFiles(selectedFiles) {
    setBusy(true); setError('')
    try {
      const uploaded = []
      for (const file of supportedFiles(selectedFiles)) uploaded.push(await uploadDocument(file, token))
      const ids = [...new Set([...documentIds, ...uploaded.map((doc) => doc.document_id)])]
      const updated = adaptPersona(await updateAgentDocuments(persona.id, ids, token))
      setDocumentIds(updated.documentIds); onDocuments(uploaded); onChanged(updated)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  async function removeDocument(documentId) {
    setBusy(true); setError('')
    try {
      const updated = adaptPersona(await updateAgentDocuments(persona.id, documentIds.filter((id) => id !== documentId), token))
      setDocumentIds(updated.documentIds); onChanged(updated)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      const saved = adaptPersona(await updateAgent(persona.id, { name, description, gender, age: age ? Number(age) : null, documentIds }, token))
      onSaved(saved)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return <form className="persona-form persona-edit-form" onSubmit={submit}>
    <Heading title={`${persona.name} 수정`} text="질문자 정보와 참고자료를 함께 변경합니다." />
    <label>이름<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
    <label>역할과 질문 성향<textarea value={description} onChange={(e) => setDescription(e.target.value)} required /></label>
    <div className="demographic-fields"><label>성별<select value={gender} onChange={(e) => setGender(e.target.value)}><option value="unspecified">선택 안 함</option><option value="female">여성</option><option value="male">남성</option><option value="other">기타</option></select></label><label>나이<input type="number" min="1" max="120" value={age} onChange={(e) => setAge(e.target.value)} /></label></div>
    <div><strong>현재 첨부자료 {linked.length}개</strong><div className="persona-source-list">{linked.length ? linked.map((doc) => <div key={doc.document_id}><span>📎 {doc.filename}</span><button type="button" disabled={busy} onClick={() => removeDocument(doc.document_id)}>삭제</button></div>) : <p>첨부된 자료가 없습니다.</p>}</div></div>
    <label className="file-button">＋ 새 자료 즉시 첨부<input hidden multiple disabled={busy} type="file" accept={ACCEPTED} onChange={(e) => { attachFiles([...e.target.files]); e.target.value = '' }} /></label>
    {error && <p className="form-error">{error}</p>}
    <div className="button-row"><button type="button" className="text-btn" onClick={onCancel}>취소</button><button className="primary-btn" disabled={busy}>{busy ? <Spinner label="수정·자료 저장 중" /> : '수정 저장'}</button></div>
  </form>
}

function ChatPanel({ result, token, documentIds, chat, update }) {
  const box = useRef(null)
  const nearBottom = useRef(true)
  const [showJump, setShowJump] = useState(false)
  const [, tick] = useState(0)
  const activeId = chat?.activeQuestionId || null
  const conversation = activeId ? chat?.conversations?.[activeId] : null
  const mutateConversation = (questionId, fn) => update((state) => ({
    ...state,
    conversations: {
      ...state.conversations,
      [questionId]: fn(state.conversations[questionId]),
    },
  }))
  useEffect(() => { if (!conversation?.sending) return; const id = setInterval(() => tick((n) => n + 1), 100); return () => clearInterval(id) }, [conversation?.sending])
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
        [q.question_id]: state.conversations[q.question_id] || {
          question: q, input: '', sending: false,
          messages: [{ id: `q-${q.question_id}`, role: 'persona', text: q.question }],
          forceScroll: true,
        },
      },
    }))
  }
  async function send(e) {
    e.preventDefault(); const questionId = activeId; const value = conversation?.input.trim(); if (!value || conversation.sending || !questionId) return
    const aid = `a-${Date.now()}`
    mutateConversation(questionId, (state) => ({ ...state, input: '', sending: true, startedAt: performance.now(), error: '', forceScroll: true, messages: [...state.messages, { id: `u-${Date.now()}`, role: 'user', text: value }, { id: aid, role: 'persona', text: '', pending: true }] }))
    try {
      const item = await streamChat({ agentId: result.persona_id, message: `예상 질문: ${conversation.question.question}\n발표자의 답변: ${value}\n답변을 평가하고 후속 질문을 해주세요.`, documentIds, responseDetail: 'detailed', token, onToken: (part) => mutateConversation(questionId, (state) => ({ ...state, messages: state.messages.map((m) => m.id === aid ? { ...m, text: m.text + part } : m) })) })
      mutateConversation(questionId, (state) => ({ ...state, sending: false, lastTiming: item.timing, messages: state.messages.map((m) => m.id === aid ? { ...m, text: item.answer, pending: false, timing: item.timing, sources: item.sources } : m) }))
    } catch (err) { mutateConversation(questionId, (state) => ({ ...state, sending: false, error: err.message, messages: state.messages.filter((m) => m.id !== aid) })) }
  }
  return <article className="chat-panel">
    <header className="chat-persona-header"><img src={result.avatar_data_url} alt={`${result.persona_name} AI 생성 아바타`} /><div><h3>{result.persona_name}</h3><p>{result.persona_role} · AI 생성 아바타</p></div>{conversation?.sending && <Spinner label={`답변 중 · ${sec(elapsed)}`} />}</header>
    <div className="question-strip">{result.questions.map((q, i) => <button className={activeId === q.question_id ? 'active' : ''} key={q.question_id} onClick={() => choose(q)}><b>Q{i + 1}</b>{q.question}</button>)}</div>
    <div className="messages" ref={box} onScroll={(e) => { const n = e.currentTarget; nearBottom.current = n.scrollHeight - n.scrollTop - n.clientHeight < 80; setShowJump(!nearBottom.current) }}>
      {!conversation && <p className="empty-state">예상 질문을 선택하세요.</p>}
      {(conversation?.messages || []).map((m) => <div className={`message ${m.role}`} key={m.id}><div>{m.text || (m.pending && <Spinner label="첫 응답 대기 중" />)}</div>{m.timing && <details className="timing"><summary>첫 응답 {sec(m.timing.first_content_latency_ms)} · 전체 {sec(m.timing.total_ms)} · {m.timing.output_lines}줄</summary><p>자료 {sec(m.timing.context_ms)} · 생성 {sec(m.timing.generation_ms)} · 저장 {sec(m.timing.save_ms)}</p></details>}</div>)}
      {showJump && <button className="jump-bottom" onClick={() => activeId && mutateConversation(activeId, (state) => ({ ...state, forceScroll: true }))}>새 메시지 보기 ↓</button>}
    </div>
    <form className="chat-composer" onSubmit={send}><textarea value={conversation?.input || ''} onChange={(e) => activeId && mutateConversation(activeId, (state) => ({ ...state, input: e.target.value }))} placeholder={conversation ? '발표자의 답변을 입력하세요' : '먼저 예상 질문을 선택하세요'} disabled={!conversation || conversation.sending} /><button className="send-btn" disabled={!conversation || conversation.sending || !conversation.input?.trim()}>전송</button></form>
    {conversation?.error && <p className="form-error">{conversation.error}</p>}
  </article>
}

const SUMMARY_STYLES = [
  { value: 'brief', label: '간단히' },
  { value: 'detailed', label: '자세히' },
  { value: 'outline', label: '개요만' },
]

function DocumentSummaryPanel({ doc, token }) {
  const [open, setOpen] = useState(false)
  const [style, setStyle] = useState('brief')
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function load(targetStyle, refresh = false) {
    setBusy(true); setError('')
    try { setData(await createSummary(doc.document_id, { style: targetStyle, refresh }, token)) } catch (err) { setError(err.message) } finally { setBusy(false) }
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
      {busy && <Spinner label="요약 생성 중" />}
      {error && <p className="form-error">{error}</p>}
      {data && !busy && <>
        <p className="summary-text">{data.summary}</p>
        {data.key_topics?.length > 0 && <ul className="summary-topics">{data.key_topics.map((topic, i) => <li key={i}><strong>{topic.topic}</strong> — {topic.description}</li>)}</ul>}
        {data.outline?.length > 0 && <ol className="summary-outline">{data.outline.map((item, i) => <li key={i}>{item}</li>)}</ol>}
      </>}
    </div>}
  </div>
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem('authToken'))
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
  const [editingPersonaId, setEditingPersonaId] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!token) { setLoading(false); return }
    let alive = true; setLoading(true)
    Promise.all([getCurrentUser(token), listDocuments(token), listAgents(token)]).then(([u, docs, agents]) => {
      if (!alive) return
      setUser(u); setDocuments(docs); setPersonas(agents.map(adaptPersona))
      const saved = JSON.parse(localStorage.getItem(`presentationWorkspace:${u.user_id}`) || '{}')
      setProjectIds((saved.projectIds || []).filter((id) => docs.some((d) => d.document_id === id)))
      setSelected((saved.selected || []).filter((id) => agents.some((p) => p.agent_id === id)).slice(0, 4))
    }).catch(() => { localStorage.removeItem('authToken'); setToken(null) }).finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [token])
  useEffect(() => { if (user) localStorage.setItem(`presentationWorkspace:${user.user_id}`, JSON.stringify({ projectIds, selected })) }, [user, projectIds, selected])
  const projectDocs = useMemo(() => documents.filter((d) => projectIds.includes(d.document_id)), [documents, projectIds])

  async function addFiles(files) {
    for (const file of files) {
      const pending = { id: `${Date.now()}-${Math.random()}`, name: file.name }; setUploads((x) => [...x, pending])
      try { const doc = await uploadDocument(file, token); setDocuments((x) => [...x.filter((d) => d.document_id !== doc.document_id), doc]); setProjectIds((x) => [...new Set([...x, doc.document_id])]) } catch (err) { setError(`${file.name}: ${err.message}`) } finally { setUploads((x) => x.filter((p) => p.id !== pending.id)) }
    }
  }
  function togglePersona(id) { setSelected((x) => x.includes(id) ? x.filter((v) => v !== id) : x.length < 4 ? [...x, id] : x) }
  async function removePersona(persona) {
    if (!window.confirm(`${persona.name} 질문자를 삭제하시겠습니까? 휴지통으로 이동합니다.`)) return
    try {
      await deleteAgent(persona.id, token)
      setPersonas((items) => items.filter((item) => item.id !== persona.id))
      setSelected((items) => items.filter((id) => id !== persona.id))
      setResults((items) => items.filter((item) => item.persona_id !== persona.id))
      setEditingPersonaId((id) => id === persona.id ? null : id)
    } catch (err) { setError(`${persona.name} 삭제 실패: ${err.message}`) }
  }
  async function makeQuestions() {
    setGenerating(true); setError(''); setResults([])
    try { const data = await generateExpectedQuestions({ personaIds: selected, presentationDocumentIds: projectIds }, token); setResults(data.results); setChats(Object.fromEntries(data.results.map((r) => [r.persona_id, { activeQuestionId: null, conversations: {} }]))) } catch (err) { setError(err.message) } finally { setGenerating(false) }
  }
  if (!token) return <Auth onLogin={setToken} />
  if (loading) return <main className="center-screen"><Spinner label="작업공간 불러오는 중" /></main>
  return <div className="workspace-shell">
    <header className="topbar"><div><span className="brand-mark small">Q</span><strong>발표 질문 시뮬레이터</strong></div><div>{user?.username}<button className="text-btn" onClick={() => { localStorage.removeItem('authToken'); setToken(null); setUser(null) }}>로그아웃</button></div></header>
    <main className="workspace-main">
      <section className="hero-copy"><span className="eyebrow">PRESENTATION WORKSPACE</span><h1>발표 자료를 기준으로<br />질문자들과 미리 대화하세요.</h1><p>발표 자료와 대본을 여러 개 넣고 최대 네 명의 질문자 관점을 동시에 준비합니다.</p></section>
      <div className="setup-grid">
        <Uploader documents={projectDocs} busyFiles={uploads} onFiles={addFiles} />
        <section className="source-block">
          <Heading title="2. 질문자 선택" text="질문자별 자료를 확인하고 수정할 수 있습니다." count={`${selected.length} / 4`} />
          <div className="persona-grid">{personas.map((p) => {
            const linked = p.documentIds.map((id) => documents.find((doc) => doc.document_id === id)).filter(Boolean)
            return <article className={`persona-entry ${selected.includes(p.id) ? 'selected' : ''}`} key={p.id}>
              <button type="button" className="persona-choice" disabled={!selected.includes(p.id) && selected.length === 4} onClick={() => togglePersona(p.id)}><span className="avatar-fallback">{p.name.slice(0, 2)}</span><span><strong>{p.name}</strong><small>{p.role} · {p.age ? `${p.age}세 · ` : ''}자료 {linked.length}개</small></span><b>{selected.includes(p.id) ? '✓' : '+'}</b></button>
              <div className="persona-inline-sources">{linked.length ? linked.map((doc) => <span key={doc.document_id}>📎 {doc.filename}</span>) : <small>첨부자료 없음</small>}</div>
              <div className="persona-actions"><button type="button" onClick={() => setEditingPersonaId((id) => id === p.id ? null : p.id)}>수정</button><button type="button" className="danger-action" onClick={() => removePersona(p)}>삭제</button></div>
              {editingPersonaId === p.id && <PersonaEditor persona={p} documents={documents} token={token} onCancel={() => setEditingPersonaId(null)} onDocuments={(docs) => setDocuments((current) => [...current, ...docs.filter((doc) => !current.some((item) => item.document_id === doc.document_id))])} onChanged={(changed) => setPersonas((items) => items.map((item) => item.id === changed.id ? changed : item))} onSaved={(saved) => { setPersonas((items) => items.map((item) => item.id === saved.id ? saved : item)); setEditingPersonaId(null) }} />}
            </article>
          })}</div>
          <PersonaCreator token={token} onCreated={(p, docs) => { setPersonas((x) => [...x, p]); setDocuments((x) => [...x, ...docs]) }} />
        </section>
      </div>
      <section className="generate-bar"><div><strong>예상 질문 준비</strong><p>발표 자료 {projectIds.length}개 · 질문자 {selected.length}명</p></div><button className="primary-btn" disabled={generating || !projectIds.length || !selected.length} onClick={makeQuestions}>{generating ? <Spinner label="페르소나별 질문 생성 중" /> : '예상 질문 생성'}</button></section>
      {error && <p className="global-error">{error}</p>}
      {results.length > 0 && <section><div className="section-title"><span className="eyebrow">PRACTICE</span><h2>페르소나별 답변 연습</h2><p>질문을 고른 뒤 답변하세요. 각 채팅창은 독립적으로 동작합니다.</p></div><div className={`chat-grid panels-${results.length}`}>{results.map((r) => <ChatPanel key={r.persona_id} result={r} token={token} documentIds={projectIds} chat={chats[r.persona_id]} update={(fn) => setChats((all) => ({ ...all, [r.persona_id]: fn(all[r.persona_id]) }))} />)}</div></section>}
      <section className="materials-overview"><div className="section-title"><span className="eyebrow">SOURCE MAP</span><h2>자료 사용 위치</h2><p>발표·페르소나·예상 질문·채팅에 사용된 위치를 표시합니다.</p></div><div className="materials-table">{documents.map((d) => { const linked = personas.filter((p) => p.documentIds.includes(d.document_id)); const used = results.some((r) => r.questions.some((q) => q.sources?.some((s) => s.document_id === d.document_id))); const chatUsed = Object.values(chats).some((chat) => Object.values(chat.conversations || {}).some((conversation) => (conversation.messages || []).some((message) => (message.sources || []).some((source) => source.document_id === d.document_id)))); return <div className="material-card" key={d.document_id}><div><strong>{d.filename}</strong><small>{d.document_type?.toUpperCase()} · {d.text_length || d.full_text?.length || 0}자</small></div><div className="usage-list">{projectIds.includes(d.document_id) && <em className="usage-badge user">사용자 발표 자료</em>}{linked.map((p) => <em className="usage-badge persona" key={p.id}>{p.name} 자료</em>)}{used && <em className="usage-badge question">예상 질문 사용</em>}{chatUsed && <em className="usage-badge chat">채팅 사용</em>}{!projectIds.includes(d.document_id) && !linked.length && <em className="usage-badge unused">미사용</em>}</div><button className="text-btn" onClick={() => setProjectIds((x) => x.includes(d.document_id) ? x.filter((id) => id !== d.document_id) : [...x, d.document_id])}>{projectIds.includes(d.document_id) ? '발표에서 제외' : '발표에 사용'}</button><DocumentSummaryPanel doc={d} token={token} /></div> })}</div></section>
    </main>
  </div>
}
