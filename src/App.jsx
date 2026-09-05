import React, { useState, useEffect, useRef } from 'react'
import {
  sendChat, createAgent, uploadDocument, listDocuments, deleteDocument,
  login, signup, getCurrentUser,
  listAgents, trashAgent, listTrashedAgents, restoreAgent, permanentlyDeleteAgent,
  listChats, trashChat, listTrashedChats, restoreChat, permanentlyDeleteChat,
} from './api'

const MAX_PERSONA_FILE_SIZE = 25 * 1024 * 1024 // 25MB, matches Backend's upload limit
const ALLOWED_PERSONA_EXTENSIONS = ['.pptx', '.pdf', '.docx']
// Backend requires a non-empty message — if the user only attaches a file and
// sends nothing, this stands in for the Backend's required message field.
const FILE_ONLY_DEFAULT_MESSAGE = '첨부한 자료의 핵심 내용을 분석해 주세요.'

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

// Single source of truth for the trash-can icon used on every delete button —
// centralized so it can't drift into a broken/inconsistent shape across spots.
function TrashIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden>
      <path
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
      />
    </svg>
  )
}

// Turns a localStorage failure into a message a non-technical user can act on.
function describeStorageError(e) {
  if (e && (e.name === 'QuotaExceededError' || e.code === 22 || e.code === 1014)) {
    return '저장 공간이 가득 차서 데이터를 저장하지 못했어요.'
  }
  if (e && e.name === 'SecurityError') {
    return '브라우저 설정(시크릿 모드, 쿠키/저장소 차단 등)으로 인해 데이터를 저장할 수 없어요. 지금 입력한 내용은 새로고침하면 사라져요.'
  }
  return '데이터를 저장하는 중 문제가 발생했어요. 방금 변경한 내용이 저장되지 않았을 수 있어요.'
}

// Backend's persona field is `agent_id` — the rest of this file calls it
// `id` throughout, so every persona coming from Backend is adapted here.
function personaFromApi(item) {
  return {
    id: item.agent_id,
    name: item.name,
    description: item.description,
    documentIds: item.document_ids || [],
  }
}

// Backend stores one record per question+answer pair. There is no chat-session
// resource, so the UI groups records by persona.
function chatFromApi(item) {
  return {
    messageId: item.message_id,
    agentId: item.agent_id,
    message: item.message,
    answer: item.answer,
    documentId: item.document_id,
    // 검색된 자료가 부족해 "자료를 추가해 달라"고 돌아온 답변인지.
    needsMoreMaterial: item.needs_more_material === true,
    createdAt: item.created_at,
  }
}

export default function App() {
  const [content, setContent] = useState('')
  const [persona, setPersona] = useState(null)
  const [sidebarExpanded, setSidebarExpanded] = useState(true)
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState(null)
  const chatAbortRef = useRef(null)
  const initStorageErrorsRef = useRef([])

  const [activeView, setActiveView] = useState('personas')
  const [sidebarMode, setSidebarMode] = useState('persona') // 'chat' | 'persona'
  const [historyQuery, setHistoryQuery] = useState('')

  const [pendingChatMaterials, setPendingChatMaterials] = useState([])
  const [documents, setDocuments] = useState([])
  const [uploadingMaterials, setUploadingMaterials] = useState([])
  const [materialError, setMaterialError] = useState(null)
  const [personaUploadProgress, setPersonaUploadProgress] = useState(null)
  const [viewingPersonaId, setViewingPersonaId] = useState(null)
  const [personaDragOver, setPersonaDragOver] = useState(false)
  const [chatDragOver, setChatDragOver] = useState(false)

  // Personas and their chat history now live on Backend — these hold the
  // fetched, authoritative copies (see the two useEffects below).
  const [personas, setPersonas] = useState([])
  const [personasError, setPersonasError] = useState(null)
  // The one thing about a persona Backend doesn't track: which files it was
  // created with. Kept locally, keyed by agent id, and namespaced per user
  // (below) so switching accounts doesn't show one user's file associations
  // under another user's session.
  const [personaMaterials, setPersonaMaterials] = useState({})

  const [chatHistory, setChatHistory] = useState([])
  const [chatHistoryLoading, setChatHistoryLoading] = useState(false)
  const [chatHistoryError, setChatHistoryError] = useState(null)

  const [personaTrash, setPersonaTrash] = useState([])
  const [personaTrashLoading, setPersonaTrashLoading] = useState(false)
  const [chatTrash, setChatTrash] = useState([])
  const [chatTrashLoading, setChatTrashLoading] = useState(false)
  const [trashActionBusyId, setTrashActionBusyId] = useState(null)

  const [newPersonaName, setNewPersonaName] = useState('')
  const [newPersonaDescription, setNewPersonaDescription] = useState('')
  const [newPersonaFiles, setNewPersonaFiles] = useState([])
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
  const [authNotice, setAuthNotice] = useState(null)
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

  // Loads the current user's own personaMaterials map whenever the logged-in
  // user changes — this is what actually keeps one account's file
  // associations from bleeding into another account's session.
  useEffect(() => {
    if (!authUser) {
      setPersonaMaterials({})
      return
    }
    try {
      setPersonaMaterials(JSON.parse(localStorage.getItem(`personaMaterials:${authUser.user_id}`) || '{}'))
    } catch (e) {
      setPersonaMaterials({})
    }
  }, [authUser?.user_id])

  useEffect(() => {
    if (!authUser) return
    try {
      localStorage.setItem(`personaMaterials:${authUser.user_id}`, JSON.stringify(personaMaterials))
    } catch (e) {
      setStorageWarning(describeStorageError(e))
    }
  }, [personaMaterials, authUser?.user_id])

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

  // A stored token is only a cache. Revalidate it at startup so an expired
  // session cannot briefly expose stale authenticated UI.
  useEffect(() => {
    if (!authToken) return
    let cancelled = false
    getCurrentUser(authToken)
      .then((user) => { if (!cancelled) setAuthUser(user) })
      .catch(() => {
        if (cancelled) return
        setAuthToken(null)
        setAuthUser(null)
        setPersonas([])
        setDocuments([])
        setChatHistory([])
        setPersona(null)
        setLoginError('로그인이 만료되었습니다. 다시 로그인해주세요.')
      })
    return () => { cancelled = true }
  }, [authToken])

  // Hydrate personas + chat history from Backend once logged in — these are
  // the authoritative lists now, not something this app invents locally.
  useEffect(() => {
    if (!authToken) return
    let cancelled = false
    setPersonasError(null)
    listAgents(authToken)
      .then((items) => { if (!cancelled) setPersonas(items.map(personaFromApi)) })
      .catch((err) => { if (!cancelled) setPersonasError(err.message || '페르소나 목록을 불러오지 못했어요.') })
    return () => { cancelled = true }
  }, [authToken])

  // Server-owned agent/document relationships replace the former
  // localStorage-only association. The existing UI map remains an adapter.
  useEffect(() => {
    const byId = new Map(documents.map((item) => [item.document_id, item]))
    const next = Object.fromEntries(personas.map((item) => {
      const linked = (item.documentIds || []).map((id) => byId.get(id)).filter(Boolean)
      return [item.id, {
        documentIds: linked.map((doc) => doc.document_id),
        fileNames: linked.map((doc) => doc.filename),
      }]
    }))
    setPersonaMaterials(next)
  }, [personas, documents])

  useEffect(() => {
    if (!authToken) return
    let cancelled = false
    listDocuments(authToken)
      .then((items) => { if (!cancelled) setDocuments(items) })
      .catch((err) => { if (!cancelled) setMaterialError(err.message || '자료 목록을 불러오지 못했어요.') })
    return () => { cancelled = true }
  }, [authToken])

  useEffect(() => {
    if (!authToken) return
    let cancelled = false
    setChatHistoryLoading(true)
    setChatHistoryError(null)
    listChats(authToken)
      .then((items) => { if (!cancelled) setChatHistory(items.map(chatFromApi)) })
      .catch((err) => { if (!cancelled) setChatHistoryError(err.message || '채팅 기록을 불러오지 못했어요.') })
      .finally(() => { if (!cancelled) setChatHistoryLoading(false) })
    return () => { cancelled = true }
  }, [authToken])

  // 페르소나/채팅 휴지통은 자주 안 쓰는 화면이라, 실제로 열었을 때만 불러온다.
  useEffect(() => {
    if (activeView !== 'materialsTrash' || sidebarMode !== 'persona' || !authToken) return
    let cancelled = false
    setPersonaTrashLoading(true)
    listTrashedAgents(authToken)
      .then((items) => { if (!cancelled) setPersonaTrash(items) })
      .catch((err) => { if (!cancelled) setMaterialError(err.message || '휴지통을 불러오지 못했어요.') })
      .finally(() => { if (!cancelled) setPersonaTrashLoading(false) })
    return () => { cancelled = true }
  }, [activeView, sidebarMode, authToken])

  useEffect(() => {
    if (activeView !== 'materialsTrash' || sidebarMode !== 'chat' || !authToken) return
    let cancelled = false
    setChatTrashLoading(true)
    listTrashedChats(authToken)
      .then((items) => { if (!cancelled) setChatTrash(items) })
      .catch((err) => { if (!cancelled) setMaterialError(err.message || '휴지통을 불러오지 못했어요.') })
      .finally(() => { if (!cancelled) setChatTrashLoading(false) })
    return () => { cancelled = true }
  }, [activeView, sidebarMode, authToken])

  // Forces a re-render every second so "경과 N초" labels on in-flight
  // uploads (and the "답변을 기다리는 중…" bubble) stay live — the elapsed
  // time itself is derived from Date.now() - startedAt at render time, this
  // state's value is unused.
  const [, setElapsedTick] = useState(0)
  useEffect(() => {
    if (uploadingMaterials.length === 0 && !personaUploadProgress && !sending) return
    const id = setInterval(() => setElapsedTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [uploadingMaterials.length, personaUploadProgress, sending])

  const threadEndRef = useRef(null)

  // On mobile the sidebar is an overlay drawer, not a permanent rail — close
  // it after any navigation so picking a chat/persona doesn't leave the
  // drawer covering the screen. No-op on desktop widths.
  useEffect(() => {
    if (window.matchMedia('(max-width: 860px)').matches) setSidebarExpanded(false)
  }, [activeView, persona])

  // Backend's /auth/login only returns a JWT, not the user's profile — so we
  // follow up with /auth/me to get { user_id, username, created_at } for
  // display. Also resets every bit of per-session UI state first, so logging
  // in as a different account never shows the previous account's persona/
  // chat selection before the fresh GET /agents + GET /chats responses land.
  async function loginAndLoadUser(username, password) {
    const { access_token } = await login({ username, password })
    const user = await getCurrentUser(access_token)
    setPersonas([])
    setChatHistory([])
    setDocuments([])
    setPersona(null)
    setViewingPersonaId(null)
    setContent('')
    setPendingChatMaterials([])
    setActiveView('personas')
    setSidebarMode('persona')
    localStorage.removeItem('persona')
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
      setAuthNotice(null)
    } catch (err) {
      setLoginError(err.message || '로그인에 실패했어요.')
    } finally {
      setLoginSubmitting(false)
    }
  }

  // Signup only creates the account — it deliberately does NOT log the user
  // in. They confirm their new credentials themselves on the login tab,
  // which also means we never risk carrying over any state from whatever
  // account (if any) was active in this browser before signing up.
  async function handleSignupSubmit(e) {
    e.preventDefault()
    if (!signupUsername.trim() || !signupPassword) return
    setSignupSubmitting(true)
    setSignupError(null)
    try {
      await signup({ username: signupUsername.trim(), password: signupPassword })
      setAuthMode('login')
      setLoginUsername(signupUsername.trim())
      setLoginPassword('')
      setLoginError(null)
      setAuthNotice('회원가입이 완료됐어요. 로그인해주세요.')
      setSignupUsername('')
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
    setPersonas([])
    setChatHistory([])
    setDocuments([])
    setPersona(null)
    setViewingPersonaId(null)
    setActiveView('personas')
    setSidebarMode('persona')
    setAuthMode('login')
    setLoginUsername('')
    setLoginPassword('')
    setLoginError(null)
    setSignupUsername('')
    setSignupPassword('')
    setSignupError(null)
  }

  function handleComposerKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      e.currentTarget.form?.requestSubmit()
    }
  }

  async function handleAdd(e) {
    e.preventDefault()
    const hasDraft = content.trim().length > 0 || pendingChatMaterials.length > 0
    if (!hasDraft) return

    const activePersona = personas.find((p) => p.id === persona) || null
    if (!activePersona) {
      setSendError('먼저 페르소나를 만들거나 선택해주세요. Backend가 페르소나 없이는 답변을 생성하지 않아요.')
      return
    }

    // A file attached to this message overrides — for this request only —
    // whatever document the persona would otherwise use.
    const activeDocumentId = pendingChatMaterials.length > 0
      ? pendingChatMaterials[pendingChatMaterials.length - 1].documentId
      : null
    const messageText = content.trim() || (activeDocumentId ? FILE_ONLY_DEFAULT_MESSAGE : '')
    if (!messageText) return

    setContent('')
    setPendingChatMaterials([])

    if (chatAbortRef.current) chatAbortRef.current.abort()
    const controller = new AbortController()
    chatAbortRef.current = controller

    const pendingId = `pending-${Date.now()}`
    setChatHistory((s) => [...s, {
      messageId: pendingId,
      agentId: activePersona.id,
      message: messageText,
      answer: null,
      documentId: activeDocumentId,
      createdAt: new Date().toISOString(),
      pending: true,
    }])

    setSending(true)
    setSendError(null)

    try {
      const item = await sendChat({
        agentId: activePersona.id,
        message: messageText,
        documentId: activeDocumentId,
        token: authToken,
        signal: controller.signal,
      })
      setChatHistory((s) => s.map((m) => (m.messageId === pendingId ? chatFromApi(item) : m)))
    } catch (err) {
      if (err.name === 'AbortError') return
      const errorMessage = err?.message || 'Backend에 연결할 수 없어요.'
      setChatHistory((s) => s.map((m) => (
        m.messageId === pendingId
          ? { ...m, pending: false, failed: true, answer: `응답 생성 실패: ${errorMessage}` }
          : m
      )))
      setSendError(errorMessage)
    } finally {
      setSending(false)
    }
  }

  // Deletes a single question+answer record — Backend's actual unit of trash.
  async function deleteExchange(messageId) {
    if (!window.confirm('삭제하시겠습니까?')) return
    const removed = chatHistory.find((m) => m.messageId === messageId)
    setTrashActionBusyId(messageId)
    setChatHistory((s) => s.filter((m) => m.messageId !== messageId))
    try {
      await trashChat(messageId, authToken)
    } catch (err) {
      if (removed) {
        setChatHistory((s) => (
          s.some((m) => m.messageId === messageId) ? s : [...s, removed]
        ))
      }
      setSendError(err.message || '삭제하지 못했어요.')
    } finally {
      setTrashActionBusyId(null)
    }
  }

  // "최근 채팅" row delete — there's no session concept server-side, so this
  // Trashes every persisted message for this persona in parallel. Failed
  // records stay visible so UI and Backend never silently diverge.
  async function deleteConversation(personaId) {
    if (!window.confirm('삭제하시겠습니까?')) return
    const targets = chatHistory.filter((m) => m.agentId === personaId && !m.pending)
    const results = await Promise.allSettled(
      targets.map((item) => trashChat(item.messageId, authToken)),
    )
    const succeeded = new Set(
      targets.filter((_, index) => results[index].status === 'fulfilled').map((m) => m.messageId),
    )
    setChatHistory((s) => s.filter((m) => !succeeded.has(m.messageId)))
    const failedCount = results.length - succeeded.size
    if (failedCount > 0) setSendError(`채팅 ${failedCount}개를 삭제하지 못했어요.`)
  }

  async function clearAllChats() {
    const targets = chatHistory.filter((m) => !m.pending)
    const results = await Promise.allSettled(
      targets.map((item) => trashChat(item.messageId, authToken)),
    )
    const succeeded = new Set(
      targets.filter((_, index) => results[index].status === 'fulfilled').map((m) => m.messageId),
    )
    setChatHistory((s) => s.filter((m) => !succeeded.has(m.messageId)))
    const failedCount = results.length - succeeded.size
    if (failedCount > 0) setSendError(`채팅 ${failedCount}개를 삭제하지 못했어요.`)
  }

  function formatTime(ts) {
    try {
      const d = new Date(ts)
      return d.toLocaleString()
    } catch (e) { return '' }
  }

  function startNewChat() {
    if (chatAbortRef.current) chatAbortRef.current.abort()
    setContent('')
    setPendingChatMaterials([])
    setPersona(null)
    setSidebarMode('chat')
    setActiveView('chats')
    setSending(false)
    setSendError(null)
  }

  function openMaterials() {
    setActiveView('materials')
  }

  function openNewPersona() {
    setNewPersonaName('')
    setNewPersonaDescription('')
    setNewPersonaFiles([])
    setPersonaFileError(null)
    setPersonaCreateError(null)
    setSidebarMode('persona')
    setActiveView('newPersona')
  }

  // Validates every picked file and keeps only the valid ones — accepted
  // files add onto whatever's already staged so users can attach across
  // multiple picks, not just one. Shared by the file picker and drag-and-drop.
  function stagePersonaFiles(fileList) {
    const files = Array.from(fileList || [])
    if (files.length === 0) return

    const accepted = []
    let firstError = null
    for (const file of files) {
      if (!ALLOWED_PERSONA_EXTENSIONS.includes(fileExtension(file.name))) {
        firstError = firstError || `${file.name}: PPTX, PDF, DOCX 파일만 올릴 수 있어요.`
        continue
      }
      if (file.size > MAX_PERSONA_FILE_SIZE) {
        firstError = firstError || `${file.name}: 파일 용량이 너무 커요 (${formatFileSize(file.size)} / 최대 25MB).`
        continue
      }
      accepted.push(file)
    }
    if (accepted.length > 0) setNewPersonaFiles((s) => [...s, ...accepted])
    setPersonaFileError(firstError)
  }

  function handlePersonaFileChange(e) {
    stagePersonaFiles(e.target.files)
    e.target.value = '' // allow re-picking the same file later
  }

  function handlePersonaFileDrop(e) {
    e.preventDefault()
    setPersonaDragOver(false)
    stagePersonaFiles(e.dataTransfer.files)
  }

  function handleChatFileDrop(e) {
    e.preventDefault()
    setChatDragOver(false)
    const files = Array.from(e.dataTransfer.files || [])
    if (files.length > 1) setMaterialError('채팅에는 한 번에 자료 하나만 첨부할 수 있어요.')
    if (files[0]) attachChatMaterial(files[0])
  }

  function removePersonaFile(index) {
    setNewPersonaFiles((s) => s.filter((_, i) => i !== index))
  }

  // Shared validation for a file attached mid-chat (same rules as persona
  // materials) — uploads immediately, then stages it for the next message.
  async function attachChatMaterial(file) {
    if (!ALLOWED_PERSONA_EXTENSIONS.includes(fileExtension(file.name))) {
      setMaterialError(`${file.name}: PPTX, PDF, DOCX 파일만 올릴 수 있어요.`)
      return
    }
    if (file.size > MAX_PERSONA_FILE_SIZE) {
      setMaterialError(`${file.name}: 파일 용량이 너무 커요 (${formatFileSize(file.size)} / 최대 25MB).`)
      return
    }
    setMaterialError(null)

    const key = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    const previousMaterial = pendingChatMaterials[0] || null
    setUploadingMaterials((s) => [...s, { key, fileName: file.name, startedAt: Date.now() }])
    try {
      const doc = await uploadDocument(file, authToken)
      if (previousMaterial && previousMaterial.documentId !== doc.document_id) {
        try {
          await deleteDocument(previousMaterial.documentId, authToken)
          setDocuments((s) => s.filter(
            (item) => item.document_id !== previousMaterial.documentId,
          ))
        } catch (cleanupError) {
          setMaterialError('새 자료는 첨부했지만 이전 임시 자료를 정리하지 못했어요.')
        }
      }
      setDocuments((s) => [doc, ...s.filter((item) => item.document_id !== doc.document_id)])
      setPendingChatMaterials([{ documentId: doc.document_id, fileName: file.name }])
    } catch (err) {
      setMaterialError(err.message || '자료를 분석하지 못했어요.')
    } finally {
      setUploadingMaterials((s) => s.filter((m) => m.key !== key))
    }
  }

  function handleChatFileChange(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    if (files.length > 1) setMaterialError('채팅에는 한 번에 자료 하나만 첨부할 수 있어요.')
    if (files[0]) attachChatMaterial(files[0])
  }

  // Removes a staged/attached material — a persona's (local-only) material,
  // or a not-yet-sent pending chat attachment. Backend has no document
  // trash, so this is a direct, confirmed removal rather than a soft delete.
  async function deleteMaterial(documentId, { personaId = null } = {}) {
    if (!window.confirm('삭제하시겠습니까?')) return
    try {
      await deleteDocument(documentId, authToken)
      setDocuments((s) => s.filter((item) => item.document_id !== documentId))
      setPendingChatMaterials((s) => s.filter((m) => m.documentId !== documentId))
      setPersonas((s) => s.map((item) => ({
        ...item,
        documentIds: (item.documentIds || []).filter((id) => id !== documentId),
      })))
      if (personaId) {
        setPersonaMaterials((s) => {
          const next = { ...s }
          delete next[personaId]
          return next
        })
      }
    } catch (err) {
      setMaterialError(err.message || '자료를 삭제하지 못했어요.')
    }
  }

  // Backend has no "template from file" concept — a document only exists as
  // context passed alongside a chat message. So creating a persona means:
  // upload the files (if any) to get document_ids, register the agent, then
  // remember the file association locally (personaMaterials).
  async function createPersona(e) {
    e.preventDefault()
    const name = newPersonaName.trim()
    const description = newPersonaDescription.trim()
    if (!name || !description) return

    setPersonaCreating(true)
    setPersonaCreateError(null)
    const documentIds = []
    let agentCreated = false
    try {
      // Uploaded one at a time (not in parallel) so the "N개 중 M번째" progress
      // readout below reflects real, meaningful steps rather than a guess.
      const fileNames = []
      for (let i = 0; i < newPersonaFiles.length; i++) {
        const file = newPersonaFiles[i]
        setPersonaUploadProgress({ index: i + 1, total: newPersonaFiles.length, startedAt: Date.now() })
        const doc = await uploadDocument(file, authToken)
        documentIds.push(doc.document_id)
        fileNames.push(file.name)
      }
      setPersonaUploadProgress(null)
      const agent = await createAgent({ name, description, documentIds }, authToken)
      agentCreated = true
      setPersonas((s) => [...s, personaFromApi(agent)])
      setDocuments((s) => [
        ...newPersonaFiles.map((file, index) => ({
          document_id: documentIds[index], filename: file.name,
        })),
        ...s.filter((item) => !documentIds.includes(item.document_id)),
      ])
      if (documentIds.length > 0) {
        setPersonaMaterials((s) => ({ ...s, [agent.agent_id]: { documentIds, fileNames } }))
      }
      setPersona(agent.agent_id)
      setNewPersonaName('')
      setNewPersonaDescription('')
      setNewPersonaFiles([])
      setPersonaFileError(null)
      setSidebarMode('chat')
      setActiveView('chats')
    } catch (err) {
      if (!agentCreated && documentIds.length > 0) {
        await Promise.allSettled(
          documentIds.map((documentId) => deleteDocument(documentId, authToken)),
        )
      }
      setPersonaCreateError(err.message || '페르소나를 만드는 중 문제가 발생했어요.')
    } finally {
      setPersonaCreating(false)
      setPersonaUploadProgress(null)
    }
  }

  // Moves the persona to Backend's trash (soft delete) — optimistic locally,
  // reconciled with an error message if Backend rejects it.
  async function deletePersona(id) {
    if (!window.confirm('삭제하시겠습니까?')) return
    const removed = personas.find((p) => p.id === id)
    setPersonas((s) => s.filter((p) => p.id !== id))
    if (persona === id) setPersona(null)
    if (viewingPersonaId === id) setActiveView('personas')
    try {
      await trashAgent(id, authToken)
    } catch (err) {
      if (removed) {
        setPersonas((s) => (s.some((p) => p.id === id) ? s : [...s, removed]))
      }
      setPersonasError(err.message || '페르소나를 삭제하지 못했어요.')
    }
  }

  // Selecting a persona from Materials/Personas just switches the active
  // persona and shows its ongoing conversation (or a blank composer if it
  // has none yet).
  function selectPersonaAndChat(personaId) {
    setPersona(personaId)
    setSidebarMode('chat')
    setActiveView('chats')
  }

  // Clicking a persona card opens its detail view (name/description + the
  // materials it was created with) instead of silently selecting it — the
  // user explicitly starts a chat from there via selectPersonaAndChat.
  function openPersonaDetail(personaId) {
    setViewingPersonaId(personaId)
    setActiveView('personaDetail')
  }

  async function handleRestorePersona(agentId) {
    setTrashActionBusyId(agentId)
    try {
      const restored = await restoreAgent(agentId, authToken)
      setPersonaTrash((s) => s.filter((x) => x.agent_id !== agentId))
      setPersonas((s) => [...s, personaFromApi(restored)])
    } catch (err) {
      setMaterialError(err.message || '복원하지 못했어요.')
    } finally {
      setTrashActionBusyId(null)
    }
  }

  async function handlePermanentlyDeletePersona(agentId) {
    if (!window.confirm('완전히 삭제하시겠습니까? 복구할 수 없습니다.')) return
    setTrashActionBusyId(agentId)
    try {
      await permanentlyDeleteAgent(agentId, authToken)
      setPersonaTrash((s) => s.filter((x) => x.agent_id !== agentId))
    } catch (err) {
      setMaterialError(err.message || '완전히 삭제하지 못했어요.')
    } finally {
      setTrashActionBusyId(null)
    }
  }

  async function handleRestoreChat(messageId) {
    setTrashActionBusyId(messageId)
    try {
      const restored = await restoreChat(messageId, authToken)
      setChatTrash((s) => s.filter((x) => x.message_id !== messageId))
      setChatHistory((s) => [...s, chatFromApi(restored)])
    } catch (err) {
      setMaterialError(err.message || '복원하지 못했어요.')
    } finally {
      setTrashActionBusyId(null)
    }
  }

  async function handlePermanentlyDeleteChat(messageId) {
    if (!window.confirm('완전히 삭제하시겠습니까? 복구할 수 없습니다.')) return
    setTrashActionBusyId(messageId)
    try {
      await permanentlyDeleteChat(messageId, authToken)
      setChatTrash((s) => s.filter((x) => x.message_id !== messageId))
    } catch (err) {
      setMaterialError(err.message || '완전히 삭제하지 못했어요.')
    } finally {
      setTrashActionBusyId(null)
    }
  }

  const activePersonaObj = personas.find((p) => p.id === persona) || null

  const personaExchanges = persona
    ? chatHistory
        .filter((m) => m.agentId === persona)
        .sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt))
    : []

  // Keeps the newest message in view as the conversation grows, instead of
  // leaving the scroll position wherever it was.
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [persona, personaExchanges.length, sending])

  // One row per persona with at least one message, most recent first — this
  // mirrors Backend's actual grouping (there's no separate "session" concept).
  const recentConversations = (() => {
    const lastByPersona = new Map()
    for (const m of chatHistory) {
      const prev = lastByPersona.get(m.agentId)
      if (!prev || new Date(m.createdAt) > new Date(prev.createdAt)) lastByPersona.set(m.agentId, m)
    }
    return Array.from(lastByPersona.entries())
      .map(([personaId, lastMessage]) => ({
        personaId,
        personaName: personas.find((p) => p.id === personaId)?.name || '삭제된 페르소나',
        lastMessage,
      }))
      .sort((a, b) => new Date(b.lastMessage.createdAt) - new Date(a.lastMessage.createdAt))
  })()

  const filteredConversations = recentConversations.filter((c) =>
    c.personaName.toLowerCase().includes(historyQuery.trim().toLowerCase())
  )

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
                onClick={() => { setAuthMode('login'); setAuthNotice(null) }}
              >
                로그인
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={authMode === 'signup'}
                className={`auth-tab ${authMode === 'signup' ? 'active' : ''}`}
                onClick={() => { setAuthMode('signup'); setAuthNotice(null) }}
              >
                회원가입
              </button>
            </div>

            {authMode === 'login' ? (
              <>
                <h3 className="auth-form-title">다시 만나서 반가워요</h3>
                {authNotice && <p className="auth-notice">{authNotice}</p>}
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
          <div className="mode-toggle" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={sidebarMode === 'persona'}
              className={`mode-toggle-btn ${sidebarMode === 'persona' ? 'active' : ''}`}
              onClick={() => { setSidebarMode('persona'); setActiveView('personas') }}
            >
              페르소나
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={sidebarMode === 'chat'}
              className={`mode-toggle-btn ${sidebarMode === 'chat' ? 'active' : ''}`}
              onClick={() => { setSidebarMode('chat'); setActiveView('chats') }}
            >
              채팅
            </button>
          </div>
        </div>

        {sidebarMode === 'chat' ? (
          <button className="new-chat-btn" onClick={() => startNewChat()}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
            <span>새 채팅</span>
          </button>
        ) : (
          <button className="new-chat-btn" onClick={() => openNewPersona()}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
            <span>새 페르소나 생성</span>
          </button>
        )}

        {sidebarMode === 'chat' && (
          <div className="sidebar-search">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.6"/><path d="M21 21l-4.3-4.3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>
            <input
              type="text"
              placeholder="채팅 검색"
              value={historyQuery}
              onChange={(e) => setHistoryQuery(e.target.value)}
            />
          </div>
        )}

        <nav className="nav-group icons">
          <div className="nav-list">
            <button className={`nav-item ${activeView === 'materials' ? 'active' : ''}`} title="자료" onClick={() => openMaterials()}>
              <span className="icon" aria-hidden>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/><path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/></svg>
              </span>
              <span className="nav-label">자료</span>
            </button>
            <button
              className={`nav-item ${activeView === 'materialsTrash' ? 'active' : ''}`}
              title={sidebarMode === 'chat' ? '채팅 휴지통' : '페르소나 휴지통'}
              onClick={() => setActiveView('materialsTrash')}
            >
              <span className="icon" aria-hidden><TrashIcon size={18} /></span>
              <span className="nav-label">{sidebarMode === 'chat' ? '채팅 휴지통' : '페르소나 휴지통'}</span>
            </button>
          </div>
        </nav>

        {sidebarMode === 'chat' && (
          <div style={{ width: '100%' }}>
            <div className="history" style={{ padding: '8px 6px 12px', maxHeight: 240, overflowY: 'auto' }}>
              <div className="section-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>최근 채팅</span>
                {recentConversations.length > 0 && (
                  <button
                    type="button"
                    className="history-clear-all"
                    onClick={() => { if (window.confirm('최근 채팅을 모두 삭제하시겠습니까?')) clearAllChats() }}
                  >
                    전체 삭제
                  </button>
                )}
              </div>
              {chatHistoryLoading && <div className="empty-hint">불러오는 중…</div>}
              {chatHistoryError && <div className="empty-hint">{chatHistoryError}</div>}
              {!chatHistoryLoading && recentConversations.length === 0 && <div className="empty-hint">이전 채팅이 없습니다.</div>}
              {!chatHistoryLoading && recentConversations.length > 0 && filteredConversations.length === 0 && <div className="empty-hint">검색 결과가 없습니다.</div>}
              {filteredConversations.map((c) => (
                <div key={c.personaId} className="history-row">
                  <button
                    className={`history-item ${persona === c.personaId ? 'active' : ''}`}
                    onClick={() => {
                      if (chatAbortRef.current) chatAbortRef.current.abort()
                      setPersona(c.personaId)
                      setActiveView('chats')
                      setSending(false)
                      setSendError(null)
                      setContent('')
                    }}
                    title={`${c.personaName} · ${formatTime(c.lastMessage.createdAt)}`}
                  >
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.personaName}</span>
                  </button>
                  <button className="history-action" aria-label="삭제" onClick={() => deleteConversation(c.personaId)}>
                    <TrashIcon size={14} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

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
          {/* Each nav button (자료/휴지통) shows only its own content — these
             views are mutually exclusive, not stacked. */}
          {activeView === 'chats' && (persona && personaExchanges.length > 0 ? (
            <div className="thread">
              <div className="thread-head">
                <h2>{activePersonaObj?.name || '알 수 없는 페르소나'}</h2>
                <p className="muted-hint">이 페르소나와의 대화예요.</p>
              </div>

              <div className="thread-messages">
                {personaExchanges.map((ex) => (
                  <div key={ex.messageId} className="thread-exchange">
                    <div className="thread-msg thread-msg-user">
                      <div className="thread-msg-bubble">{ex.message}</div>
                    </div>
                    <div className="thread-msg thread-msg-assistant">
                      <div className={`thread-msg-bubble ${ex.pending ? 'thread-msg-bubble-loading' : ''}`}>
                        {ex.pending && !ex.answer
                          ? `답변을 기다리는 중… (경과 ${Math.floor((Date.now() - new Date(ex.createdAt).getTime()) / 1000)}초)`
                          : ex.answer}
                        {ex.needsMoreMaterial && (
                          <p className="thread-msg-material-hint">
                            관련 자료를 찾지 못했어요. 발표 자료를 첨부하면 그 내용을 근거로 답변해요.
                          </p>
                        )}
                      </div>
                    </div>
                    {!ex.pending && (
                      <button
                        className="thread-exchange-delete history-action"
                        aria-label="이 대화 삭제"
                        onClick={() => deleteExchange(ex.messageId)}
                      >
                        <TrashIcon size={13} />
                      </button>
                    )}
                  </div>
                ))}
                {sendError && <p className="assistant-reply-error">{sendError}</p>}
                <div ref={threadEndRef} />
              </div>

              {pendingChatMaterials.length > 0 && (
                <ul className="persona-file-list composer-material-list">
                  {pendingChatMaterials.map((m) => (
                    <li key={m.documentId}>
                      <span>📎 {m.fileName}</span>
                      <button type="button" onClick={() => deleteMaterial(m.documentId)} aria-label={`${m.fileName} 제거`}>×</button>
                    </li>
                  ))}
                </ul>
              )}

              <form
                className={`add-form hero-form thread-composer ${chatDragOver ? 'drag-over' : ''}`}
                onSubmit={handleAdd}
                onDragOver={(e) => { e.preventDefault(); setChatDragOver(true) }}
                onDragLeave={() => setChatDragOver(false)}
                onDrop={handleChatFileDrop}
              >
                <textarea
                  placeholder="메시지를 입력하세요"
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  onKeyDown={handleComposerKeyDown}
                />
                <div className="hero-form-actions">
                  <label className="composer-attach-btn" title="자료 첨부">
                    <input
                      type="file"
                      accept=".pptx,.pdf,.docx"
                      onChange={handleChatFileChange}
                      className="visually-hidden"
                    />
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M21.44 11.05l-9.19 9.19a5 5 0 01-7.07-7.07l9.19-9.19a3.5 3.5 0 014.95 4.95l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </label>
                  <button type="submit" className="hero-send-btn" disabled={sending || (!content.trim() && pendingChatMaterials.length === 0)} aria-label="전송">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </button>
                </div>
              </form>
              {uploadingMaterials.map((u) => (
                <div key={u.key} className="upload-status">
                  <span className="upload-status-bar" />
                  분석하는 중이에요… {u.fileName} (경과 {Math.floor((Date.now() - u.startedAt) / 1000)}초)
                </div>
              ))}
              {materialError && <p className="persona-file-error">{materialError}</p>}
            </div>
          ) : (
            <div className="hero">
              <div className="hero-avatar"></div>
              <h1>오늘은 어떤 발표를 도와드릴까요?</h1>
              {persona ? (
                <p>선택된 페르소나: <strong>{activePersonaObj?.name}</strong></p>
              ) : (
                <p className="muted-hint">아직 선택된 페르소나가 없어요. 페르소나를 먼저 만들어야 대화를 시작할 수 있어요.</p>
              )}

              {pendingChatMaterials.length > 0 && (
                <ul className="persona-file-list composer-material-list">
                  {pendingChatMaterials.map((m) => (
                    <li key={m.documentId}>
                      <span>📎 {m.fileName}</span>
                      <button type="button" onClick={() => deleteMaterial(m.documentId)} aria-label={`${m.fileName} 제거`}>×</button>
                    </li>
                  ))}
                </ul>
              )}

              <form
                className={`add-form hero-form ${chatDragOver ? 'drag-over' : ''}`}
                onSubmit={handleAdd}
                onDragOver={(e) => { e.preventDefault(); setChatDragOver(true) }}
                onDragLeave={() => setChatDragOver(false)}
                onDrop={handleChatFileDrop}
              >
                <textarea
                  placeholder={persona ? '메시지를 입력하세요' : '먼저 페르소나를 만들거나 선택해주세요'}
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  onKeyDown={handleComposerKeyDown}
                  disabled={!persona}
                />
                <div className="hero-form-actions">
                  <label className="composer-attach-btn" title="자료 첨부">
                    <input
                      type="file"
                      accept=".pptx,.pdf,.docx"
                      onChange={handleChatFileChange}
                      className="visually-hidden"
                      disabled={!persona}
                    />
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M21.44 11.05l-9.19 9.19a5 5 0 01-7.07-7.07l9.19-9.19a3.5 3.5 0 014.95 4.95l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </label>
                  <button type="submit" className="hero-send-btn" disabled={sending || !persona || (!content.trim() && pendingChatMaterials.length === 0)} aria-label="전송">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </button>
                </div>
              </form>
              {uploadingMaterials.map((u) => (
                <div key={u.key} className="upload-status">
                  <span className="upload-status-bar" />
                  분석하는 중이에요… {u.fileName} (경과 {Math.floor((Date.now() - u.startedAt) / 1000)}초)
                </div>
              ))}
              {materialError && <p className="persona-file-error">{materialError}</p>}
              {!persona && (
                <button type="button" className="empty-cta" onClick={() => openNewPersona()} style={{ marginTop: 12 }}>
                  + 첫 페르소나 만들기
                </button>
              )}
            </div>
          ))}

          {activeView === 'materials' && sidebarMode === 'persona' && (
            <div className="materials-panel panel">
              <div className="view-icon">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/><path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>
              </div>
              <h3>자료</h3>
              <p className="panel-intro">페르소나를 만들 때 올린 자료 목록입니다.</p>
              {materialError && <p className="persona-file-error">{materialError}</p>}
              {(() => {
                const rows = personas.flatMap((p) => {
                  const entry = personaMaterials[p.id]
                  return (entry?.fileNames || []).map((fileName, idx) => ({
                    key: entry.documentIds[idx],
                    documentId: entry.documentIds[idx],
                    fileName,
                    personaId: p.id,
                    personaName: p.name,
                  }))
                })
                return rows.length === 0 ? (
                  <div className="panel-empty-state">
                    <p className="muted-hint">아직 업로드한 자료가 없습니다.</p>
                    <button type="button" className="empty-cta" onClick={() => openNewPersona()}>+ 페르소나 만들며 자료 올리기</button>
                  </div>
                ) : (
                  <div className="materials-list">
                    {rows.map((m) => (
                      <div key={m.key} className="material-row">
                        <button className="template-pick" onClick={() => selectPersonaAndChat(m.personaId)}>
                          <span className="template-pick-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/><path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>
                          </span>
                          <span className="template-pick-body">
                            <b>{m.fileName}</b>
                            <span>{m.personaName} 페르소나에 연결됨</span>
                          </span>
                        </button>
                        <button className="history-action" aria-label={`${m.fileName} 삭제`} onClick={() => deleteMaterial(m.documentId, { personaId: m.personaId })}>
                          <TrashIcon size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                )
              })()}
            </div>
          )}
          {activeView === 'materials' && sidebarMode === 'chat' && (
            <div className="materials-panel panel">
              <div className="view-icon">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/><path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>
              </div>
              <h3>자료</h3>
              <p className="panel-intro">다음 메시지에 첨부할 자료예요. 전송하면 그 메시지 하나에만 사용되고 목록에서 사라져요.</p>
              {materialError && <p className="persona-file-error">{materialError}</p>}
              {pendingChatMaterials.length === 0 ? (
                <div className="panel-empty-state">
                  <p className="muted-hint">아직 첨부한 자료가 없습니다.</p>
                </div>
              ) : (
                <div className="materials-list">
                  {pendingChatMaterials.map((m) => (
                    <div key={m.documentId} className="material-row">
                      <div className="template-pick template-pick-static">
                        <span className="template-pick-icon">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/><path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>
                        </span>
                        <span className="template-pick-body"><b>{m.fileName}</b></span>
                      </div>
                      <button className="history-action" aria-label={`${m.fileName} 삭제`} onClick={() => deleteMaterial(m.documentId)}>
                        <TrashIcon size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {activeView === 'materialsTrash' && sidebarMode === 'persona' && (
            <div className="materials-panel panel">
              <div className="view-icon"><TrashIcon size={22} /></div>
              <h3>페르소나 휴지통</h3>
              <p className="panel-intro">삭제한 페르소나를 복원하거나 완전히 삭제할 수 있어요.</p>
              {materialError && <p className="persona-file-error">{materialError}</p>}
              {personaTrashLoading ? (
                <p className="muted-hint">불러오는 중…</p>
              ) : personaTrash.length === 0 ? (
                <div className="panel-empty-state">
                  <p className="muted-hint">휴지통이 비어있어요.</p>
                </div>
              ) : (
                <div className="materials-list">
                  {personaTrash.map((item) => (
                    <div key={item.agent_id} className="material-row">
                      <div className="template-pick template-pick-static">
                        <span className="template-pick-icon">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><circle cx="12" cy="8" r="3.2" stroke="currentColor" strokeWidth="1.2"/><path d="M5 20c0-3.6 3.1-6.2 7-6.2s7 2.6 7 6.2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>
                        </span>
                        <span className="template-pick-body">
                          <b>{item.name}</b>
                          <span>{item.description}</span>
                        </span>
                      </div>
                      {trashActionBusyId === item.agent_id ? (
                        <span className="status-deleting">처리 중…</span>
                      ) : (
                        <>
                          <button type="button" className="trash-restore-btn" onClick={() => handleRestorePersona(item.agent_id)}>복원</button>
                          <button className="history-action" aria-label={`${item.name} 완전 삭제`} onClick={() => handlePermanentlyDeletePersona(item.agent_id)}>
                            <TrashIcon size={14} />
                          </button>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {activeView === 'materialsTrash' && sidebarMode === 'chat' && (
            <div className="materials-panel panel">
              <div className="view-icon"><TrashIcon size={22} /></div>
              <h3>채팅 휴지통</h3>
              <p className="panel-intro">삭제한 대화를 복원하거나 완전히 삭제할 수 있어요.</p>
              {materialError && <p className="persona-file-error">{materialError}</p>}
              {chatTrashLoading ? (
                <p className="muted-hint">불러오는 중…</p>
              ) : chatTrash.length === 0 ? (
                <div className="panel-empty-state">
                  <p className="muted-hint">휴지통이 비어있어요.</p>
                </div>
              ) : (
                <div className="materials-list">
                  {chatTrash.map((item) => (
                    <div key={item.message_id} className="material-row">
                      <div className="template-pick template-pick-static">
                        <span className="template-pick-icon">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/><path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>
                        </span>
                        <span className="template-pick-body">
                          <b>{item.message}</b>
                          <span>{personas.find((p) => p.id === item.agent_id)?.name || '알 수 없는 페르소나'} · {formatTime(item.created_at)}</span>
                        </span>
                      </div>
                      {trashActionBusyId === item.message_id ? (
                        <span className="status-deleting">처리 중…</span>
                      ) : (
                        <>
                          <button type="button" className="trash-restore-btn" onClick={() => handleRestoreChat(item.message_id)}>복원</button>
                          <button className="history-action" aria-label="완전 삭제" onClick={() => handlePermanentlyDeleteChat(item.message_id)}>
                            <TrashIcon size={14} />
                          </button>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {activeView === 'newPersona' && (
            <div className="new-persona-panel panel">
              <h3>새 페르소나 만들기</h3>
              <p className="panel-intro">이름과 평가 관점을 설명하고, 원하면 PPTX나 PDF, DOCX 참고 자료를 올려보세요(여러 개 가능).</p>
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
                <label
                  className={`file-drop ${personaDragOver ? 'drag-over' : ''}`}
                  onDragOver={(e) => { e.preventDefault(); setPersonaDragOver(true) }}
                  onDragLeave={() => setPersonaDragOver(false)}
                  onDrop={handlePersonaFileDrop}
                >
                  <input
                    type="file"
                    accept=".pptx,.pdf,.docx"
                    multiple
                    onChange={handlePersonaFileChange}
                    className="visually-hidden"
                  />
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M12 16V4M12 4l-4 4M12 4l4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  <span>{newPersonaFiles.length > 0 ? `${newPersonaFiles.length}개 자료 선택됨` : personaDragOver ? '여기에 놓으세요' : 'PPTX, PDF, DOCX 자료 올리기 (선택, 여러 개 가능 · 드래그 가능)'}</span>
                </label>
                {newPersonaFiles.length > 0 && (
                  <ul className="persona-file-list">
                    {newPersonaFiles.map((f, i) => (
                      <li key={`${f.name}-${i}`}>
                        <span>{f.name}</span>
                        <button type="button" onClick={() => removePersonaFile(i)} aria-label={`${f.name} 제거`}>×</button>
                      </li>
                    ))}
                  </ul>
                )}
                {personaFileError && <p className="persona-file-error">{personaFileError}</p>}
                {personaCreateError && <p className="persona-file-error">{personaCreateError}</p>}
                <p className="new-persona-note">* 자료를 올리면 Backend가 문서를 분석해 대화의 참고 문맥으로 사용해요.</p>
                {personaUploadProgress && (
                  <div className="upload-status">
                    <span className="upload-status-bar" />
                    자료를 분석하는 중이에요… ({personaUploadProgress.index}/{personaUploadProgress.total}, 경과 {Math.floor((Date.now() - personaUploadProgress.startedAt) / 1000)}초)
                  </div>
                )}
                <div style={{ display: 'flex', gap: 8 }}>
                  <button type="submit" className="new-persona-submit" disabled={personaCreating || !newPersonaName.trim() || !newPersonaDescription.trim()}>
                    {personaCreating ? '만드는 중…' : '만들기'}
                  </button>
                  <button type="button" className="new-persona-cancel" onClick={() => setActiveView('personas')}>취소</button>
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
                <p className="panel-intro">만들어둔 페르소나 목록이에요. 카드를 클릭하면 자료를 볼 수 있어요.</p>
                {personasError && <p className="persona-file-error">{personasError}</p>}
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
                      onClick={() => openPersonaDetail(p.id)}
                      role="button"
                      tabIndex={0}
                      aria-label={`${p.name} 자료 보기`}
                      onKeyDown={activateOnKey(() => openPersonaDetail(p.id))}
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
                        <div className="persona-tag">
                          {(() => {
                            const fileNames = personaMaterials[p.id]?.fileNames
                            return fileNames && fileNames.length > 0
                              ? `${fileNames[0]}${fileNames.length > 1 ? ` 외 ${fileNames.length - 1}개` : ''}`
                              : '텍스트 전용 페르소나'
                          })()}
                        </div>
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
          {activeView === 'personaDetail' && (() => {
            const p = personas.find((x) => x.id === viewingPersonaId)
            if (!p) {
              return (
                <div className="new-persona-panel panel">
                  <p className="muted-hint">삭제된 페르소나예요.</p>
                  <button type="button" className="new-persona-cancel" onClick={() => setActiveView('personas')}>← 목록으로</button>
                </div>
              )
            }
            const entry = personaMaterials[p.id]
            const materials = (entry?.fileNames || []).map((fileName, idx) => ({
              documentId: entry.documentIds[idx],
              fileName,
            }))
            return (
              <div className="new-persona-panel panel">
                <div className="view-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><circle cx="12" cy="8" r="3.2" stroke="currentColor" strokeWidth="1.4"/><path d="M5 20c0-3.6 3.1-6.2 7-6.2s7 2.6 7 6.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>
                </div>
                <h3>{p.name}</h3>
                <p className="panel-intro">{p.description}</p>
                <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginBottom: 18 }}>
                  <button type="button" className="new-persona-submit" onClick={() => selectPersonaAndChat(p.id)}>이 페르소나로 채팅 시작</button>
                  <button type="button" className="new-persona-cancel" onClick={() => deletePersona(p.id)}>페르소나 삭제</button>
                </div>
                <p className="section-label" style={{ padding: 0, textAlign: 'left' }}>첨부한 자료</p>
                {materialError && <p className="persona-file-error">{materialError}</p>}
                {materials.length === 0 ? (
                  <p className="muted-hint">첨부한 자료가 없어요.</p>
                ) : (
                  <div className="materials-list">
                    {materials.map((m) => (
                      <div key={m.documentId} className="material-row">
                        <div className="template-pick template-pick-static">
                          <span className="template-pick-icon">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/><path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>
                          </span>
                          <span className="template-pick-body"><b>{m.fileName}</b></span>
                        </div>
                        <button className="history-action" aria-label={`${m.fileName} 삭제`} onClick={() => deleteMaterial(m.documentId, { personaId: p.id })}>
                          <TrashIcon size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <button type="button" className="new-persona-cancel" style={{ marginTop: 18 }} onClick={() => setActiveView('personas')}>← 목록으로</button>
              </div>
            )
          })()}
        </main>
      </div>
    </div>
  )
}
