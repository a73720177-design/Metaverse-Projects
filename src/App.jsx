import React, { useState, useEffect, useRef } from 'react'
import { createAgent, sendChat, uploadDocument } from './api'

const MAX_PERSONA_FILE_SIZE = 25 * 1024 * 1024
const ALLOWED_PERSONA_EXTENSIONS = ['.pptx', '.pdf', '.docx']

function fileExtension(fileName) {
  const match = /\.[^.]+$/.exec(fileName)
  return match ? match[0].toLowerCase() : ''
}

function formatFileSize(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
  return `${Math.ceil(bytes / 1024)}KB`
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
  const [assistantReply, setAssistantReply] = useState('')
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
  // Personas are entirely user-created (optionally backed by an uploaded PPTX/PDF/DOCX) — starts blank.
  const [personas, setPersonas] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('personas') || '[]')
    } catch (e) {
      initStorageErrorsRef.current.push('저장된 페르소나가 손상되어 불러오지 못했어요. 페르소나 목록이 초기화됐어요.')
      return []
    }
  })
  const [newPersonaName, setNewPersonaName] = useState('')
  const [newPersonaDescription, setNewPersonaDescription] = useState('')
  const [newPersonaFiles, setNewPersonaFiles] = useState([])
  const [personaFileError, setPersonaFileError] = useState(null)
  const [personaSubmitting, setPersonaSubmitting] = useState(false)
  const [storageWarning, setStorageWarning] = useState(null)
  const personaGridRef = useRef(null)

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
    try {
      localStorage.setItem('personas', JSON.stringify(personas))
    } catch (e) {
      setStorageWarning(describeStorageError(e))
    }
  }, [personas])

  async function handleAdd(e) {
    e.preventDefault()
    const message = content.trim()
    if (!message || sending) return

    const userMessage = { role: 'user', content: message }
    const existingChat = chats.find((c) => c.id === selectedChatId) || null
    const intendedPersonaId = existingChat?.persona || persona
    const selectedPersona = personas.find((p) => p.id === intendedPersonaId)
    if (!selectedPersona?.agentId) {
      setSendError('Backend에 등록된 페르소나를 먼저 만들어 선택해주세요.')
      return
    }

    let chatId
    let personaIdForRequest

    if (existingChat) {
      // Continue the open thread — keep using the persona it was started
      // with, not whatever's currently selected in the sidebar.
      chatId = existingChat.id
      const historyForRequest = [...existingChat.messages, userMessage]
      personaIdForRequest = existingChat.persona
      setChats((s) => s.map((c) => (c.id === chatId ? { ...c, messages: historyForRequest } : c)))
    } else {
      chatId = Date.now()
      const historyForRequest = [userMessage]
      personaIdForRequest = persona
      const newChat = {
        id: chatId,
        title: content.slice(0, 40) || '(제목 없음)',
        persona,
        createdAt: chatId,
        messages: historyForRequest,
      }
      setChats((s) => [newChat, ...s])
      setSelectedChatId(chatId)
    }

    setContent('')

    if (streamAbortRef.current) streamAbortRef.current.abort()
    const controller = new AbortController()
    streamAbortRef.current = controller

    setSending(true)
    setAssistantReply('')
    setSendError(null)

    try {
      const response = await sendChat({
        agentId: selectedPersona?.agentId,
        message: userMessage.content,
        documentId: selectedPersona?.documentId || null,
        signal: controller.signal,
      })
      const fullReply = response.answer
      setChats((s) => s.map((c) => (
        c.id === chatId
          ? { ...c, messages: [...c.messages, { role: 'assistant', content: fullReply }] }
          : c
      )))
    } catch (err) {
      if (err.name !== 'AbortError') {
        setSendError(err?.message || 'Backend에 연결할 수 없습니다.')
      }
    } finally {
      setSending(false)
      setAssistantReply('')
      if (streamAbortRef.current === controller) streamAbortRef.current = null
    }
  }

  function deleteChat(id) {
    setChats((s) => s.filter((c) => c.id !== id))
    if (selectedChatId === id) {
      setSelectedChatId(null)
      setContent('')
      setAssistantReply('')
      setSendError(null)
    }
  }

  function clearAllChats() {
    setChats([])
    setSelectedChatId(null)
    setContent('')
    setAssistantReply('')
    setSendError(null)
  }

  function formatTime(ts) {
    try {
      const d = new Date(ts)
      return d.toLocaleString()
    } catch (e) { return '' }
  }

  const templates = Object.fromEntries(personas.map((p) => [p.id, p.template]))

  // When user switches persona, if inputs are empty, prefill them with the persona
  // template — but only for a brand-new conversation, not mid-thread.
  useEffect(() => {
    if (!content && !selectedChatId) {
      const tpl = templates[persona] || ''
      setContent(tpl)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persona])

  function startNewChat() {
    if (streamAbortRef.current) streamAbortRef.current.abort()
    setContent('')
    setActiveView('chats')
    setSelectedChatId(null)
    setSending(false)
    setAssistantReply('')
    setSendError(null)
  }

  function openPersonas() {
    setActiveView('personas')
    // scroll persona rail into view
    setTimeout(() => {
      if (personaGridRef.current) personaGridRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 120)
  }

  function openMaterials() {
    setActiveView('materials')
  }

  // Deliberately load a persona's template into the composer, overwriting any
  // current draft, and start a fresh conversation with it.
  function applyPersonaTemplate(personaId) {
    const tpl = templates[personaId] || ''
    setPersona(personaId)
    setContent(tpl)
    setSelectedChatId(null)
    setActiveView('chats')
  }

  function openNewPersona() {
    setNewPersonaName('')
    setNewPersonaDescription('')
    setNewPersonaFiles([])
    setPersonaFileError(null)
    setActiveView('newPersona')
  }

  function handlePersonaFileChange(e) {
    const selected = Array.from(e.target.files || [])
    e.target.value = '' // allow re-picking the same file(s) later
    if (selected.length === 0) return

    const accepted = []
    const errors = []
    for (const file of selected) {
      if (!ALLOWED_PERSONA_EXTENSIONS.includes(fileExtension(file.name))) {
        errors.push(`${file.name}: PPTX, PDF, DOCX 파일만 올릴 수 있어요.`)
        continue
      }
      if (file.size > MAX_PERSONA_FILE_SIZE) {
        errors.push(`${file.name}: 파일 용량이 너무 커요 (${formatFileSize(file.size)} / 최대 25MB).`)
        continue
      }
      accepted.push(file)
    }

    if (accepted.length > 0) {
      setNewPersonaFiles([accepted[0]])
      if (!newPersonaName.trim()) {
        setNewPersonaName(accepted[0].name.replace(/\.[^.]+$/, ''))
      }
    }
    setPersonaFileError(errors.length > 0 ? errors.join(' ') : null)
  }

  function removePersonaFile(index) {
    setNewPersonaFiles((s) => s.filter((_, i) => i !== index))
  }

  async function createPersona(e) {
    e.preventDefault()
    const name = newPersonaName.trim()
    const description = newPersonaDescription.trim()
    if (!name || !description || personaSubmitting) return

    setPersonaSubmitting(true)
    setPersonaFileError(null)
    try {
      const agent = await createAgent({ name, description })
      const uploaded = newPersonaFiles[0]
        ? await uploadDocument(newPersonaFiles[0])
        : null
      const id = agent.agent_id
      const template = uploaded
        ? `${uploaded.filename} 자료를 참고해서 발표를 검토해주세요.`
        : `${name}의 관점에서 발표를 검토해주세요.`
      const p = {
        id,
        agentId: agent.agent_id,
        name: agent.name,
        description,
        template,
        documentId: uploaded?.document_id || null,
        fileNames: uploaded ? [uploaded.filename] : null,
      }
      setPersonas((s) => [...s, p])
      setPersona(id)
      setContent(template)
      setNewPersonaName('')
      setNewPersonaDescription('')
      setNewPersonaFiles([])
      setSelectedChatId(null)
      setActiveView('chats')
    } catch (err) {
      setPersonaFileError(err?.message || '페르소나를 만들지 못했습니다.')
    } finally {
      setPersonaSubmitting(false)
    }
  }

  function deletePersona(id) {
    setPersonas((s) => s.filter((p) => p.id !== id))
    if (persona === id) setPersona(null)
  }

  const filteredChats = chats.filter((c) =>
    c.title.toLowerCase().includes(historyQuery.trim().toLowerCase())
  )

  const activeChat = chats.find((c) => c.id === selectedChatId) || null
  const personaIdInView = activeChat ? activeChat.persona : persona

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
            <div className="brand-toggle-wrap">
              <button className="collapse-btn" onClick={() => setSidebarExpanded((v) => !v)} aria-label="사이드바 확장" aria-expanded={sidebarExpanded}>
                {sidebarExpanded ? '‹' : '›'}
              </button>
            </div>
          </div>
        </div>

        <button className="new-chat-btn" onClick={() => startNewChat()}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
          <span>새 채팅</span>
        </button>

        <div className="sidebar-search">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><circle cx="11" cy="11" r="7" stroke="#9a978c" strokeWidth="1.6"/><path d="M21 21l-4.3-4.3" stroke="#9a978c" strokeWidth="1.6" strokeLinecap="round"/></svg>
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
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" stroke="#475569" strokeWidth="1.2" strokeLinejoin="round"/><path d="M14 3v5h5" stroke="#475569" strokeWidth="1.2" strokeLinejoin="round"/></svg>
              </span>
              <span className="nav-label">자료</span>
            </button>
            <button className={`nav-item ${activeView === 'personas' ? 'active' : ''}`} title="페르소나" onClick={() => openPersonas()}>
              <span className="icon" aria-hidden>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="8" r="3.2" stroke="#475569" strokeWidth="1.2"/><path d="M5 20c0-3.6 3.1-6.2 7-6.2s7 2.6 7 6.2" stroke="#475569" strokeWidth="1.2" strokeLinecap="round"/></svg>
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
            {chats.length === 0 && <div style={{ color: '#94a3b8', padding: '8px 10px' }}>이전 채팅이 없습니다.</div>}
            {chats.length > 0 && filteredChats.length === 0 && <div style={{ color: '#94a3b8', padding: '8px 10px' }}>검색 결과가 없습니다.</div>}
            {filteredChats.map((c) => (
              <div key={c.id} className="history-row">
                <button
                  className={`history-item ${selectedChatId === c.id ? 'active' : ''}`}
                  onClick={() => {
                    if (streamAbortRef.current) streamAbortRef.current.abort()
                    setSelectedChatId(c.id)
                    setActiveView('chats')
                    setSending(false)
                    setAssistantReply('')
                    setSendError(null)
                    setContent('')
                  }}
                  title={`${c.title} · ${formatTime(c.createdAt)}`}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.title}</span>
                </button>
                <button className="history-action" aria-label="삭제" onClick={() => deleteChat(c.id)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 6h18" stroke="#64748b" strokeWidth="1.5" strokeLinecap="round"/><path d="M8 6v12a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2V6" stroke="#64748b" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M10 11v5M14 11v5" stroke="#64748b" strokeWidth="1.5" strokeLinecap="round"/></svg>
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
                title={p.fileNames?.length ? `${p.name} (${p.fileNames.join(', ')})` : p.name}
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
          <div className="avatar-sm avatar-sm-guest">API</div>
          <div className="foot-user">
            <b>Backend 연결 모드</b>
            <span>로그인은 현재 MVP 범위에서 제외</span>
          </div>
        </div>
      </aside>

      <div className="container">
        <main className="content">
          {activeChat ? (
            <div className="thread">
              <div className="thread-head">
                <h2>{activeChat.title}</h2>
                {personaIdInView ? (
                  <p>선택된 페르소나: <strong>{personas.find(p => p.id === personaIdInView)?.name}</strong></p>
                ) : (
                  <p style={{ color: '#9ca3af' }}>페르소나 없이 진행 중인 대화예요.</p>
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
                    <div className="thread-msg-bubble">{assistantReply}<span className="assistant-reply-cursor" /></div>
                  </div>
                )}
                {sendError && <p className="assistant-reply-error">{sendError}</p>}
              </div>

              <form className="add-form hero-form thread-composer" onSubmit={handleAdd}>
                <textarea
                  placeholder="메시지를 입력하세요"
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  maxLength={5000}
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
                <p style={{ color: '#9ca3af' }}>아직 선택된 페르소나가 없어요. 아래에서 만들어보세요.</p>
              )}

              <form className="add-form hero-form" onSubmit={handleAdd}>
                <textarea
                  placeholder="메시지를 입력하세요"
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  maxLength={5000}
                />
                <div className="hero-form-actions">
                  <button type="submit" className="hero-send-btn" disabled={sending || !content} aria-label="전송">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* View-specific panels */}
          {activeView === 'materials' && (
            <div className="materials-panel" style={{ marginTop: 14, maxWidth: 760, width: '100%' }}>
              <h3>자료</h3>
              <p style={{ color: '#6b7280', marginBottom: 10 }}>페르소나를 만들 때 올린 자료 목록입니다.</p>
              {personas.filter((p) => p.fileNames?.length).length === 0 && (
                <p style={{ color: '#9ca3af' }}>아직 업로드한 자료가 없습니다.</p>
              )}
              {personas.filter((p) => p.fileNames?.length).map((p) => (
                <button key={p.id} className="template-pick" onClick={() => applyPersonaTemplate(p.id)}>
                  <b>{p.fileNames.join(', ')}</b>
                  <span>{p.name} 페르소나에 연결됨</span>
                </button>
              ))}
            </div>
          )}
          {activeView === 'newPersona' && (
            <div className="new-persona-panel" style={{ marginTop: 14, maxWidth: 760, width: '100%' }}>
              <h3>새 페르소나 만들기</h3>
              <p style={{ color: '#6b7280', marginBottom: 10 }}>이름을 정하고, 원하면 PPTX나 PDF, DOCX 같은 참고 자료를 함께 올려보세요.</p>
              <form className="new-persona-form" onSubmit={createPersona}>
                <input
                  placeholder="페르소나 이름 — 예: 투자 발표용"
                  value={newPersonaName}
                  onChange={(e) => setNewPersonaName(e.target.value)}
                  maxLength={100}
                  required
                />
                <textarea
                  placeholder="평가자의 전문 분야와 평가 기준을 설명해주세요."
                  value={newPersonaDescription}
                  onChange={(e) => setNewPersonaDescription(e.target.value)}
                  maxLength={5000}
                  required
                />
                <label className="file-drop">
                  <input
                    type="file"
                    accept=".pptx,.pdf,.docx"
                    onChange={handlePersonaFileChange}
                    style={{ display: 'none' }}
                  />
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 16V4M12 4l-4 4M12 4l4 4" stroke="#7c3aed" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" stroke="#7c3aed" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  <span>{newPersonaFiles.length > 0 ? newPersonaFiles[0].name : 'PPTX, PDF, DOCX 자료 올리기 (선택)'}</span>
                </label>
                {newPersonaFiles.length > 0 && (
                  <ul className="persona-file-list">
                    {newPersonaFiles.map((f, i) => (
                      <li key={`${f.name}-${f.size}-${i}`}>
                        <span>{f.name}</span>
                        <button type="button" onClick={() => removePersonaFile(i)} aria-label={`${f.name} 제거`}>×</button>
                      </li>
                    ))}
                  </ul>
                )}
                {personaFileError && <p className="persona-file-error">{personaFileError}</p>}
                <p className="new-persona-note">* 선택한 파일은 Backend에 업로드되어 채팅 문맥으로 사용됩니다.</p>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button type="submit" className="new-persona-submit" disabled={personaSubmitting || !newPersonaName.trim() || !newPersonaDescription.trim()}>
                    {personaSubmitting ? 'Backend에 등록 중…' : '만들기'}
                  </button>
                  <button type="button" className="new-persona-cancel" disabled={personaSubmitting} onClick={() => setActiveView('chats')}>취소</button>
                </div>
              </form>
            </div>
          )}

          <div className="persona-rail" ref={personaGridRef}>
            <div className="persona-grid">
              {personas.length === 0 && (
                <div className="persona-empty">아직 만든 페르소나가 없어요. 아래에서 첫 페르소나를 만들어보세요.</div>
              )}
              {personas.map((p, idx) => (
                  <div key={p.id} className="persona-card" onClick={() => setPersona(p.id)}>
                  <button
                    className="persona-card-remove"
                    aria-label={`${p.name} 삭제`}
                    onClick={(e) => { e.stopPropagation(); deletePersona(p.id) }}
                  >
                    ×
                  </button>
                  <div className="persona-top">
                    <div className="persona-avatar" data-n={idx+1}></div>
                    <div>
                      <div className="persona-name">{p.name}</div>
                      <div className="persona-tag">{p.fileNames?.length ? p.fileNames.join(', ') : `페르소나 ${idx+1}`}</div>
                    </div>
                  </div>
                  <div className="persona-desc">{p.name} 스타일로 대화를 시작합니다.</div>
                </div>
              ))}
              <div className="persona-card add" onClick={() => openNewPersona()}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
                <span>새 페르소나 추가</span>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
