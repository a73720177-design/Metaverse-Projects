import React, { useState, useEffect, useRef } from 'react'
import { sendChat, createAgent, getAgents, deleteAgent, uploadDocument, login, signup, getCurrentUser } from './api'

const MAX_PERSONA_FILE_SIZE = 25 * 1024 * 1024 // 25MB, matches Backend's upload limit
const ALLOWED_PERSONA_EXTENSIONS = ['.pptx', '.pdf', '.docx']

function fileExtension(fileName) {
  const match = /\.[^.]+$/.exec(fileName)
  return match ? match[0].toLowerCase() : ''
}

function formatFileSize(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
  return `${Math.ceil(bytes / 1024)}KB`
}

// Lets a non-<button> clickable element (e.g. a card containing its own
// nested button, where a real <button> wrapper would be invalid HTML)
// respond to Enter/Space like a real button for keyboard users.
function activateOnKey(handler) {
  return (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handler(e)
    }
  }
}

// Turns a localStorage failure into a message a non-technical user can act on.
function describeStorageError(e) {
  if (e && (e.name === 'QuotaExceededError' || e.code === 22 || e.code === 1014)) {
    return '저장 공간이 가득 차서 데이터를 저장하지 못했어요. "전체 삭제"로 오래된 채팅을 정리해주세요.'
  }
  if (e && e.name === 'SecurityError') {
    return '브라우저 설정(시크릿 모드, 쿠키/저장소 차단 등)으로 인해 데이터를 저장할 수 없어요. 지금 입력한 내용은 새로고침하면 사라져요.'
  }
  return '데이터를 저장하는 중 문제가 발생했어요. 방금 변경한 내용이 저장되지 않았을 수 있어요.'
}

export default function App() {
  const [content, setContent] = useState('')
  const [persona, setPersona] = useState(null)
  const [sidebarExpanded, setSidebarExpanded] = useState(true)
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState(null)
  const streamAbortRef = useRef(null)
  const initStorageErrorsRef = useRef([])
  const [chats, setChats] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('chats') || '[]')
    } catch (e) {
      initStorageErrorsRef.current.push('저장된 채팅 기록이 손상되어 불러오지 못했어요. 채팅 목록이 초기화됐어요.')
      return []
    }
  })
  const [selectedChatId, setSelectedChatId] = useState(null)
  const [activeView, setActiveView] = useState('chats')
  const [historyQuery, setHistoryQuery] = useState('')
  const [personas, setPersonas] = useState([])
  const [newPersonaName, setNewPersonaName] = useState('')
  const [newPersonaDescription, setNewPersonaDescription] = useState('')
  const [newPersonaFile, setNewPersonaFile] = useState(null)
  const [personaFileError, setPersonaFileError] = useState(null)
  const [personaCreating, setPersonaCreating] = useState(false)
  const [personaCreateError, setPersonaCreateError] = useState(null)
  const [storageWarning, setStorageWarning] = useState(null)
  const [authUser, setAuthUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('authUser') || 'null')
    } catch (e) {
      return null
    }
  })
  const [authToken, setAuthToken] = useState(() => localStorage.getItem('authToken') || null)
  const [authMode, setAuthMode] = useState('login') // 'login' | 'signup'
  const [loginUsername, setLoginUsername] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginError, setLoginError] = useState(null)
  const [loginSubmitting, setLoginSubmitting] = useState(false)
  const [signupUsername, setSignupUsername] = useState('')
  const [signupPassword, setSignupPassword] = useState('')
  const [signupError, setSignupError] = useState(null)
  const [signupSubmitting, setSignupSubmitting] = useState(false)

  useEffect(() => {
    if (initStorageErrorsRef.current.length > 0) {
      setStorageWarning(initStorageErrorsRef.current.join(' '))
    }
  }, [])

  useEffect(() => {
    const p = localStorage.getItem('persona')
    if (p) setPersona(p)
  }, [])

  useEffect(() => {
    if (persona) localStorage.setItem('persona', persona)
    else localStorage.removeItem('persona')
  }, [persona])

  useEffect(() => {
    try {
      localStorage.setItem('chats', JSON.stringify(chats))
    } catch (e) {
      setStorageWarning(describeStorageError(e))
    }
  }, [chats])

  useEffect(() => {
    if (!authToken || !authUser) {
      setPersonas([])
      setPersona(null)
      return undefined
    }

    const controller = new AbortController()
    getAgents(authToken, controller.signal)
      .then((agents) => {
        const ownedPersonas = agents.map((agent) => ({
          id: agent.agent_id,
          name: agent.name,
          description: agent.description,
        }))
        setPersonas(ownedPersonas)
        setPersona((selectedId) => (
          ownedPersonas.some((ownedPersona) => ownedPersona.id === selectedId) ? selectedId : null
        ))
      })
      .catch((error) => {
        if (error.name !== 'AbortError') setStorageWarning(error.message || '페르소나 목록을 불러오지 못했어요.')
      })
    return () => controller.abort()
  }, [authToken, authUser?.user_id])

  useEffect(() => {
    try {
      if (authUser) localStorage.setItem('authUser', JSON.stringify(authUser))
      else localStorage.removeItem('authUser')
      if (authToken) localStorage.setItem('authToken', authToken)
      else localStorage.removeItem('authToken')
    } catch (e) {
      setStorageWarning(describeStorageError(e))
    }
  }, [authUser, authToken])

  // On mobile the sidebar is an overlay drawer, not a permanent rail — close
  // it after any navigation so picking a chat/persona doesn't leave the
  // drawer covering the screen. No-op on desktop widths.
  useEffect(() => {
    if (window.matchMedia('(max-width: 860px)').matches) setSidebarExpanded(false)
  }, [activeView, selectedChatId])

  // Backend's /auth/login only returns a JWT, not the user's profile — so we
  // follow up with /auth/me to get { user_id, username, created_at } for display.
  async function loginAndLoadUser(username, password) {
    const { access_token } = await login({ username, password })
    const user = await getCurrentUser(access_token)
    setAuthToken(access_token)
    setAuthUser(user)
  }

  async function handleLoginSubmit(e) {
    e.preventDefault()
    if (!loginUsername.trim() || !loginPassword) return
    setLoginSubmitting(true)
    setLoginError(null)
    try {
      await loginAndLoadUser(loginUsername.trim(), loginPassword)
      setLoginPassword('')
    } catch (err) {
      setLoginError(err.message || '로그인에 실패했어요.')
    } finally {
      setLoginSubmitting(false)
    }
  }

  // Backend's /auth/signup only creates the account (no token) — log in with
  // the same credentials right after so signup feels like one step.
  async function handleSignupSubmit(e) {
    e.preventDefault()
    if (!signupUsername.trim() || !signupPassword) return
    setSignupSubmitting(true)
    setSignupError(null)
    try {
      await signup({ username: signupUsername.trim(), password: signupPassword })
      await loginAndLoadUser(signupUsername.trim(), signupPassword)
      setSignupPassword('')
    } catch (err) {
      setSignupError(err.message || '회원가입에 실패했어요.')
    } finally {
      setSignupSubmitting(false)
    }
  }

  function handleLogout() {
    setAuthToken(null)
    setAuthUser(null)
    setAuthMode('login')
    setLoginUsername('')
    setLoginPassword('')
    setLoginError(null)
    setSignupUsername('')
    setSignupPassword('')
    setSignupError(null)
  }

  async function handleAdd(e) {
    e.preventDefault()
    if (!content) return

    const existingChat = chats.find((c) => c.id === selectedChatId) || null
    const personaIdForRequest = existingChat ? existingChat.persona : persona
    const activePersona = personas.find((p) => p.id === personaIdForRequest) || null

    if (!activePersona) {
      setSendError('먼저 페르소나를 만들거나 선택해주세요. Backend가 페르소나 없이는 답변을 생성하지 않아요.')
      return
    }

    const userMessage = { role: 'user', content }
    const messageText = content

    let chatId
    if (existingChat) {
      // Continue the open thread — keep using the persona it was started
      // with, not whatever's currently selected in the sidebar.
      chatId = existingChat.id
      setChats((s) => s.map((c) => (c.id === chatId ? { ...c, messages: [...c.messages, userMessage] } : c)))
    } else {
      chatId = Date.now()
      const newChat = {
        id: chatId,
        title: content.slice(0, 40) || '(제목 없음)',
        persona: personaIdForRequest,
        createdAt: chatId,
        messages: [userMessage],
      }
      setChats((s) => [newChat, ...s])
      setSelectedChatId(chatId)
    }

    setContent('')

    if (streamAbortRef.current) streamAbortRef.current.abort()
    const controller = new AbortController()
    streamAbortRef.current = controller

    setSending(true)
    setSendError(null)

    try {
      const { answer } = await sendChat({
        agentId: activePersona.id,
        message: messageText,
        documentId: activePersona.documentId,
        token: authToken,
        signal: controller.signal,
      })
      setChats((s) => s.map((c) => (
        c.id === chatId ? { ...c, messages: [...c.messages, { role: 'assistant', content: answer }] } : c
      )))
    } catch (err) {
      if (err.name === 'AbortError') return
      setSendError(err?.message || 'Backend에 연결할 수 없어요. src/api.js의 API 주소가 실제 Backend와 맞는지 확인해주세요.')
    } finally {
      setSending(false)
    }
  }

  function deleteChat(id) {
    setChats((s) => s.filter((c) => c.id !== id))
    if (selectedChatId === id) {
      setSelectedChatId(null)
      setContent('')
      setSendError(null)
    }
  }

  function clearAllChats() {
    setChats([])
    setSelectedChatId(null)
    setContent('')
    setSendError(null)
  }

  function formatTime(ts) {
    try {
      const d = new Date(ts)
      return d.toLocaleString()
    } catch (e) { return '' }
  }

  function startNewChat() {
    if (streamAbortRef.current) streamAbortRef.current.abort()
    setContent('')
    setActiveView('chats')
    setSelectedChatId(null)
    setSending(false)
    setSendError(null)
  }

  function openPersonas() {
    setActiveView('personas')
  }

  function openMaterials() {
    setActiveView('materials')
  }

  function openNewPersona() {
    setNewPersonaName('')
    setNewPersonaDescription('')
    setNewPersonaFile(null)
    setPersonaFileError(null)
    setPersonaCreateError(null)
    setActiveView('newPersona')
  }

  function handlePersonaFileChange(e) {
    const file = e.target.files?.[0] || null
    e.target.value = '' // allow re-picking the same file later
    if (!file) return

    if (!ALLOWED_PERSONA_EXTENSIONS.includes(fileExtension(file.name))) {
      setPersonaFileError(`${file.name}: PPTX, PDF, DOCX 파일만 올릴 수 있어요.`)
      return
    }
    if (file.size > MAX_PERSONA_FILE_SIZE) {
      setPersonaFileError(`${file.name}: 파일 용량이 너무 커요 (${formatFileSize(file.size)} / 최대 25MB).`)
      return
    }

    setNewPersonaFile(file)
    setPersonaFileError(null)
  }

  function removePersonaFile() {
    setNewPersonaFile(null)
  }

  // Backend has no "template from file" concept — a document only exists as
  // context passed alongside a chat message. So creating a persona means:
  // upload the file (if any) to get a document_id, register the agent to get
  // an agent_id, then keep both together as the local persona record.
  async function createPersona(e) {
    e.preventDefault()
    const name = newPersonaName.trim()
    const description = newPersonaDescription.trim()
    if (!name || !description) return

    setPersonaCreating(true)
    setPersonaCreateError(null)
    try {
      let documentId = null
      if (newPersonaFile) {
        const doc = await uploadDocument(newPersonaFile, authToken)
        documentId = doc.document_id
      }
      const agent = await createAgent({ name, description }, authToken)
      const p = {
        id: agent.agent_id,
        name,
        description,
        documentId,
        fileName: newPersonaFile ? newPersonaFile.name : null,
      }
      setPersonas((s) => [...s, p])
      setPersona(p.id)
      setNewPersonaName('')
      setNewPersonaDescription('')
      setNewPersonaFile(null)
      setPersonaFileError(null)
      setSelectedChatId(null)
      setActiveView('chats')
    } catch (err) {
      setPersonaCreateError(err.message || '페르소나를 만드는 중 문제가 발생했어요.')
    } finally {
      setPersonaCreating(false)
    }
  }

  async function deletePersona(id) {
    try {
      await deleteAgent(id, authToken)
      setPersonas((s) => s.filter((p) => p.id !== id))
      if (persona === id) setPersona(null)
    } catch (err) {
      setStorageWarning(err.message || '페르소나를 삭제하지 못했어요.')
    }
  }

  // Selecting a persona from Materials/Personas just switches the active
  // persona and starts a fresh conversation with it — Backend has no
  // per-persona template text to preload the composer with.
  function selectPersonaAndChat(personaId) {
    setPersona(personaId)
    setSelectedChatId(null)
    setActiveView('chats')
  }

  const filteredChats = chats.filter((c) =>
    c.title.toLowerCase().includes(historyQuery.trim().toLowerCase())
  )

  const activeChat = chats.find((c) => c.id === selectedChatId) || null
  const personaIdInView = activeChat ? activeChat.persona : persona

  if (!authUser) {
    return (
      <div className="auth-page">
        <div className="auth-modal">
          <div className="auth-panel auth-panel-brand">
            <div className="auth-brand-row">
              <div className="brand-mark">PH</div>
              <div className="auth-brand-name">발표 도우미</div>
            </div>
            <h2 className="auth-headline">발표 전,<br />더 단단한 피드백.</h2>
            <p className="auth-subline">내 발표자료를 분석하고, 맞춤 페르소나로 실전처럼 연습하세요.</p>
            <div className="auth-chip-row">
              <span className="auth-chip">자료 분석</span>
              <span className="auth-chip">맞춤 페르소나</span>
              <span className="auth-chip">실시간 피드백</span>
            </div>
          </div>

          <div className="auth-panel auth-panel-form">
            <div className="auth-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={authMode === 'login'}
                className={`auth-tab ${authMode === 'login' ? 'active' : ''}`}
                onClick={() => setAuthMode('login')}
              >
                로그인
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={authMode === 'signup'}
                className={`auth-tab ${authMode === 'signup' ? 'active' : ''}`}
                onClick={() => setAuthMode('signup')}
              >
                회원가입
              </button>
            </div>

            {authMode === 'login' ? (
              <>
                <h3 className="auth-form-title">다시 만나서 반가워요</h3>
                <form onSubmit={handleLoginSubmit} className="auth-form">
                  <label>
                    아이디
                    <input
                      type="text"
                      autoFocus
                      value={loginUsername}
                      onChange={(e) => setLoginUsername(e.target.value)}
                      placeholder="영문, 숫자, _ (3~32자)"
                      pattern="[A-Za-z0-9_]+"
                      minLength={3}
                      maxLength={32}
                      required
                    />
                  </label>
                  <label>
                    비밀번호
                    <input
                      type="password"
                      value={loginPassword}
                      onChange={(e) => setLoginPassword(e.target.value)}
                      placeholder="비밀번호"
                      required
                    />
                  </label>
                  {loginError && <p className="auth-error">{loginError}</p>}
                  <button type="submit" className="auth-submit" disabled={loginSubmitting || !loginUsername.trim() || !loginPassword}>
                    {loginSubmitting ? '로그인 중…' : '로그인'}
                  </button>
                </form>
              </>
            ) : (
              <>
                <h3 className="auth-form-title">환영해요, 시작해볼까요</h3>
                <form onSubmit={handleSignupSubmit} className="auth-form">
                  <label>
                    아이디
                    <input
                      type="text"
                      autoFocus
                      value={signupUsername}
                      onChange={(e) => setSignupUsername(e.target.value)}
                      placeholder="영문, 숫자, _ (3~32자)"
                      pattern="[A-Za-z0-9_]+"
                      minLength={3}
                      maxLength={32}
                      required
                    />
                  </label>
                  <label>
                    비밀번호
                    <input
                      type="password"
                      value={signupPassword}
                      onChange={(e) => setSignupPassword(e.target.value)}
                      placeholder="8자 이상"
                      minLength={8}
                      required
                    />
                  </label>
                  {signupError && <p className="auth-error">{signupError}</p>}
                  <button type="submit" className="auth-submit" disabled={signupSubmitting || !signupUsername.trim() || !signupPassword}>
                    {signupSubmitting ? '가입하는 중…' : '가입하기'}
                  </button>
                </form>
              </>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={`app ${sidebarExpanded ? 'expanded' : ''}`}>
      {storageWarning && (
        <div className="storage-warning" role="alert">
          <span>{storageWarning}</span>
          <button type="button" onClick={() => setStorageWarning(null)} aria-label="닫기">×</button>
        </div>
      )}
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-row">
            <div className="brand-mark">PH</div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <div className="brand-name">발표 도우미</div>
            </div>
          </div>
        </div>

        <button className="new-chat-btn" onClick={() => startNewChat()}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
          <span>새 채팅</span>
        </button>

        <div className="sidebar-search">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.6"/><path d="M21 21l-4.3-4.3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>
          <input
            type="text"
            placeholder="채팅 검색"
            value={historyQuery}
            onChange={(e) => setHistoryQuery(e.target.value)}
          />
        </div>

        <nav className="nav-group icons">
          <div className="nav-list">
            <button className={`nav-item ${activeView === 'materials' ? 'active' : ''}`} title="자료" onClick={() => openMaterials()}>
              <span className="icon" aria-hidden>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/><path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/></svg>
              </span>
              <span className="nav-label">자료</span>
            </button>
            <button className={`nav-item ${activeView === 'personas' ? 'active' : ''}`} title="페르소나" onClick={() => openPersonas()}>
              <span className="icon" aria-hidden>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="8" r="3.2" stroke="currentColor" strokeWidth="1.2"/><path d="M5 20c0-3.6 3.1-6.2 7-6.2s7 2.6 7 6.2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>
              </span>
              <span className="nav-label">페르소나</span>
            </button>
          </div>
        </nav>

        <div style={{ width: '100%' }}>
          <div className="history" style={{ padding: '8px 6px 12px', maxHeight: 240, overflowY: 'auto' }}>
            <div className="section-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>최근 채팅</span>
              {chats.length > 0 && (
                <button
                  type="button"
                  className="history-clear-all"
                  onClick={() => { if (window.confirm('최근 채팅을 모두 삭제할까요?')) clearAllChats() }}
                >
                  전체 삭제
                </button>
              )}
            </div>
            {chats.length === 0 && <div className="empty-hint">이전 채팅이 없습니다.</div>}
            {chats.length > 0 && filteredChats.length === 0 && <div className="empty-hint">검색 결과가 없습니다.</div>}
            {filteredChats.map((c) => (
              <div key={c.id} className="history-row">
                <button
                  className={`history-item ${selectedChatId === c.id ? 'active' : ''}`}
                  onClick={() => {
                    if (streamAbortRef.current) streamAbortRef.current.abort()
                    setSelectedChatId(c.id)
                    setActiveView('chats')
                    setSending(false)
                    setSendError(null)
                    setContent('')
                  }}
                  title={`${c.title} · ${formatTime(c.createdAt)}`}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.title}</span>
                </button>
                <button className="history-action" aria-label="삭제" onClick={() => deleteChat(c.id)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 6h18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/><path d="M8 6v12a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2V6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M10 11v5M14 11v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="section-label" style={{ marginTop: 6 }}>페르소나</div>
        <div className="persona-selector">
          {personas.map((p) => (
            <div key={p.id} className="persona-dot-wrap">
              <button
                className={`persona-dot ${persona === p.id ? 'active' : ''}`}
                title={p.fileName ? `${p.name} (${p.fileName})` : p.name}
                onClick={() => { setPersona(p.id); setActiveView('chats') }}
              >
                {p.name.slice(0,1)}
              </button>
              <button
                className="persona-dot-remove"
                aria-label={`${p.name} 삭제`}
                onClick={(e) => { e.stopPropagation(); deletePersona(p.id) }}
              >
                ×
              </button>
            </div>
          ))}
          <button className="persona-dot persona-dot-add" title="새 페르소나 추가" onClick={() => openNewPersona()}>+</button>
        </div>

        <div className="sidebar-foot">
          <div className="avatar-sm">{(authUser.username || '유').slice(0, 1).toUpperCase()}</div>
          <div className="foot-user">
            <b>{authUser.username}</b>
            <span>{formatTime(authUser.created_at)} 가입</span>
          </div>
          <button type="button" className="logout-btn" onClick={handleLogout}>로그아웃</button>
        </div>
      </aside>

      {sidebarExpanded && (
        <div className="sidebar-backdrop" onClick={() => setSidebarExpanded(false)} aria-hidden />
      )}

      <button
        className="sidebar-toggle"
        onClick={() => setSidebarExpanded((v) => !v)}
        aria-label={sidebarExpanded ? '사이드바 접기' : '사이드바 펼치기'}
        aria-expanded={sidebarExpanded}
        title={sidebarExpanded ? '사이드바 접기' : '사이드바 펼치기'}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden>
          <path d={sidebarExpanded ? 'M15 5l-7 7 7 7' : 'M9 5l7 7-7 7'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>

      <div className="container">
        <main className="content">
          {/* Each nav button (자료/페르소나) shows only its own content — these
             views are mutually exclusive, not stacked. */}
          {activeView === 'chats' && (activeChat ? (
            <div className="thread">
              <div className="thread-head">
                <h2>{activeChat.title}</h2>
                {personaIdInView ? (
                  <p>선택된 페르소나: <strong>{personas.find(p => p.id === personaIdInView)?.name}</strong></p>
                ) : (
                  <p className="muted-hint">페르소나 없이 진행 중인 대화예요.</p>
                )}
              </div>

              <div className="thread-messages">
                {activeChat.messages.map((m, i) => (
                  <div key={i} className={`thread-msg thread-msg-${m.role}`}>
                    <div className="thread-msg-bubble">{m.content}</div>
                  </div>
                ))}
                {sending && (
                  <div className="thread-msg thread-msg-assistant">
                    <div className="thread-msg-bubble thread-msg-bubble-loading">답변을 기다리는 중…</div>
                  </div>
                )}
                {sendError && <p className="assistant-reply-error">{sendError}</p>}
              </div>

              <form className="add-form hero-form thread-composer" onSubmit={handleAdd}>
                <textarea
                  placeholder="메시지를 입력하세요"
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                />
                <div className="hero-form-actions">
                  <button type="submit" className="hero-send-btn" disabled={sending || !content} aria-label="전송">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </button>
                </div>
              </form>
            </div>
          ) : (
            <div className="hero">
              <div className="hero-avatar"></div>
              <h1>오늘은 어떤 발표를 도와드릴까요?</h1>
              {persona ? (
                <p>선택된 페르소나: <strong>{personas.find(p=>p.id===persona)?.name}</strong></p>
              ) : (
                <p className="muted-hint">아직 선택된 페르소나가 없어요. 페르소나를 먼저 만들어야 대화를 시작할 수 있어요.</p>
              )}

              <form className="add-form hero-form" onSubmit={handleAdd}>
                <textarea
                  placeholder={persona ? '메시지를 입력하세요' : '먼저 페르소나를 만들거나 선택해주세요'}
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  disabled={!persona}
                />
                <div className="hero-form-actions">
                  <button type="submit" className="hero-send-btn" disabled={sending || !content || !persona} aria-label="전송">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </button>
                </div>
              </form>
              {!persona && (
                <button type="button" className="empty-cta" onClick={() => openNewPersona()} style={{ marginTop: 12 }}>
                  + 첫 페르소나 만들기
                </button>
              )}
            </div>
          ))}

          {activeView === 'materials' && (
            <div className="materials-panel panel">
              <div className="view-icon">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/><path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>
              </div>
              <h3>자료</h3>
              <p className="panel-intro">페르소나를 만들 때 올린 자료 목록입니다.</p>
              {personas.filter((p) => p.fileName).length === 0 ? (
                <div className="panel-empty-state">
                  <p className="muted-hint">아직 업로드한 자료가 없습니다.</p>
                  <button type="button" className="empty-cta" onClick={() => openNewPersona()}>+ 페르소나 만들며 자료 올리기</button>
                </div>
              ) : (
                <div className="materials-list">
                  {personas.filter((p) => p.fileName).map((p) => (
                    <button key={p.id} className="template-pick" onClick={() => selectPersonaAndChat(p.id)}>
                      <span className="template-pick-icon">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/><path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>
                      </span>
                      <span className="template-pick-body">
                        <b>{p.fileName}</b>
                        <span>{p.name} 페르소나에 연결됨</span>
                      </span>
                      <svg className="template-pick-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M9 5l7 7-7 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {activeView === 'newPersona' && (
            <div className="new-persona-panel panel">
              <h3>새 페르소나 만들기</h3>
              <p className="panel-intro">이름과 평가 관점을 설명하고, 원하면 PPTX나 PDF, DOCX 참고 자료를 한 개 올려보세요.</p>
              <form className="new-persona-form" onSubmit={createPersona}>
                <input
                  placeholder="페르소나 이름 — 예: 근거 중심 평가자"
                  value={newPersonaName}
                  onChange={(e) => setNewPersonaName(e.target.value)}
                />
                <textarea
                  placeholder="이 페르소나가 어떤 관점으로 평가할지 설명해주세요 — 예: 발표의 주장과 실험 근거를 중요하게 평가한다."
                  value={newPersonaDescription}
                  onChange={(e) => setNewPersonaDescription(e.target.value)}
                  rows={3}
                />
                <label className="file-drop">
                  <input
                    type="file"
                    accept=".pptx,.pdf,.docx"
                    onChange={handlePersonaFileChange}
                    className="visually-hidden"
                  />
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 16V4M12 4l-4 4M12 4l4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  <span>{newPersonaFile ? newPersonaFile.name : 'PPTX, PDF, DOCX 자료 올리기 (선택, 1개)'}</span>
                </label>
                {newPersonaFile && (
                  <ul className="persona-file-list">
                    <li>
                      <span>{newPersonaFile.name}</span>
                      <button type="button" onClick={removePersonaFile} aria-label={`${newPersonaFile.name} 제거`}>×</button>
                    </li>
                  </ul>
                )}
                {personaFileError && <p className="persona-file-error">{personaFileError}</p>}
                {personaCreateError && <p className="persona-file-error">{personaCreateError}</p>}
                <p className="new-persona-note">* 자료를 올리면 Backend가 문서를 분석해 대화의 참고 문맥으로 사용해요.</p>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button type="submit" className="new-persona-submit" disabled={personaCreating || !newPersonaName.trim() || !newPersonaDescription.trim()}>
                    {personaCreating ? '만드는 중…' : '만들기'}
                  </button>
                  <button type="button" className="new-persona-cancel" onClick={() => setActiveView('chats')}>취소</button>
                </div>
              </form>
            </div>
          )}

          {activeView === 'personas' && (
            <div className="persona-rail">
              <div className="persona-rail-intro">
                <div className="view-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><circle cx="12" cy="8" r="3.2" stroke="currentColor" strokeWidth="1.4"/><path d="M5 20c0-3.6 3.1-6.2 7-6.2s7 2.6 7 6.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>
                </div>
                <h3>페르소나 {personas.length > 0 && <span className="persona-count">{personas.length}</span>}</h3>
                <p className="panel-intro">만들어둔 페르소나 목록이에요. 카드를 클릭하면 선택돼요.</p>
              </div>
              <div className="persona-grid">
                {personas.length === 0 && (
                  <div className="persona-empty">
                    <div className="persona-empty-icon">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><circle cx="12" cy="8" r="3.2" stroke="currentColor" strokeWidth="1.4"/><path d="M5 20c0-3.6 3.1-6.2 7-6.2s7 2.6 7 6.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>
                    </div>
                    <p>아직 만든 페르소나가 없어요.</p>
                    <button type="button" className="empty-cta" onClick={() => openNewPersona()}>+ 첫 페르소나 만들기</button>
                  </div>
                )}
                {personas.map((p, idx) => (
                    <div
                      key={p.id}
                      className="persona-card"
                      style={{ animationDelay: `${Math.min(idx, 8) * 40}ms` }}
                      onClick={() => setPersona(p.id)}
                      role="button"
                      tabIndex={0}
                      aria-label={`${p.name} 페르소나 선택`}
                      onKeyDown={activateOnKey(() => setPersona(p.id))}
                    >
                    <button
                      className="persona-card-remove"
                      aria-label={`${p.name} 삭제`}
                      onClick={(e) => { e.stopPropagation(); deletePersona(p.id) }}
                    >
                      ×
                    </button>
                    <div className="persona-top">
                      <div className="persona-avatar" data-n={p.name.slice(0, 1)}></div>
                      <div>
                        <div className="persona-name">{p.name}</div>
                        <div className="persona-tag">{p.fileName || '텍스트 전용 페르소나'}</div>
                      </div>
                    </div>
                    <div className="persona-desc">{p.description}</div>
                  </div>
                ))}
                {personas.length > 0 && (
                  <div
                    className="persona-card add"
                    onClick={() => openNewPersona()}
                    role="button"
                    tabIndex={0}
                    aria-label="새 페르소나 추가"
                    onKeyDown={activateOnKey(() => openNewPersona())}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
                    <span>새 페르소나 추가</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
