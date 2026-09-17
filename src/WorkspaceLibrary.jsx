import React, { useEffect, useMemo, useRef, useState } from 'react'
import * as api from './api'
import LoadingProgress from './LoadingProgress'
import { chatPromptPreview, groupChatsByConversation } from './workspace-utils.mjs'

export function CoverageNotice({ coverage }) {
  if (!coverage) return <small>분석 범위 정보 없음</small>
  return <p className="grounding-note">{coverage.truncated ? '일부 구간 분석' : '전체 구간 분석'} · {coverage.analyzed_chunks}/{coverage.total_chunks}개 구간</p>
}

function Evidence({ sources = [] }) {
  if (!sources.length) return null
  return <details className="library-evidence"><summary>참고 근거 {sources.length}개</summary><ul>{sources.map((s, i) => <li key={`${s.document_id || s.filename}-${s.page || 0}-${i}`}><strong>{s.filename || '참고자료'}{s.page ? ` · ${s.page}쪽/슬라이드` : ''}</strong>{s.excerpt && <blockquote>{s.excerpt}</blockquote>}</li>)}</ul></details>
}

const VERDICT_LABELS = {
  supported: '근거 있음', partially_supported: '일부 근거 있음', contradicted: '자료와 상충',
  overgeneralized: '과도한 일반화', insufficient_evidence: '근거 부족', not_verifiable: '검증 불가',
}

export default function WorkspaceLibrary({ token, model, documents, personas, onResume, onChanged }) {
  const [tab, setTab] = useState('reviews')
  const [items, setItems] = useState([])
  const [trashPersonas, setTrashPersonas] = useState([])
  const [review, setReview] = useState(null)
  const [agent, setAgent] = useState('')
  const [documentId, setDocumentId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const sessionCache = useRef(new Map())
  const chatGroups = useMemo(() => tab === 'chats' ? groupChatsByConversation(items) : [], [items, tab])
  const personaName = (id) => personas.find((p) => (p.id || p.agent_id) === id)?.name || '삭제된 질문자'
  const documentName = (id) => documents.find((d) => d.document_id === id)?.filename || '삭제된 발표 자료'
  const revealPractice = () => requestAnimationFrame(() => document.getElementById('practice-workspace')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))

  useEffect(() => {
    const controller = new AbortController()
    setBusy(true); setError('')
    const load = tab === 'reviews' ? api.listReviews : tab === 'sessions' ? api.listPracticeSessions : tab === 'chats' ? api.listChats : api.listTrashedChats
    Promise.all([load(token, controller.signal), tab === 'trash' ? api.listTrashedAgents(token, controller.signal) : []])
      .then(([rows, agents]) => { if (!controller.signal.aborted) { setItems(rows); setTrashPersonas(agents) } })
      .catch((e) => { if (e.name !== 'AbortError') setError(e.message) })
      .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [tab, token, revision])

  async function action(work, changed = false) {
    setBusy(true); setError('')
    try {
      await work()
      if (changed) { await onChanged(); setRevision((n) => n + 1) }
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  async function resume(id) {
    const [session, chats] = await Promise.all([api.getPracticeSession(id, token), api.listChats(token)])
    sessionCache.current.set(id, session)
    onResume(session, chats)
    revealPractice()
  }

  async function openConversation(group) {
    if (!group.conversationId) throw new Error('이 대화는 이전 형식으로 저장되어 연습 화면에서 다시 열 수 없습니다.')
    const summaries = await api.listPracticeSessions(token)
    for (const summary of summaries) {
      const session = sessionCache.current.get(summary.session_id) || await api.getPracticeSession(summary.session_id, token)
      sessionCache.current.set(summary.session_id, session)
      const found = session.response?.results?.some((result) => result.questions?.some((question) => question.conversation_id === group.conversationId))
      if (found) {
        onResume(session, items, { conversationId: group.conversationId })
        revealPractice()
        return
      }
    }
    throw new Error('이 대화와 연결된 연습 기록을 찾지 못했습니다. 질문자나 연습 기록이 삭제됐는지 확인해주세요.')
  }

  function permanent(work) {
    if (window.confirm('완전히 삭제하면 복구할 수 없습니다. 삭제하시겠습니까?')) action(work, true)
  }

  const tabs = [['reviews', '자료 리뷰'], ['sessions', '연습 기록'], ['chats', '대화 이력'], ['trash', '휴지통']]
  const isEmpty = !busy && !items.length && (tab !== 'trash' || !trashPersonas.length)

  return <section className="source-block workspace-library">
    <div className="library-heading"><div><span className="eyebrow">REVIEW LIBRARY</span><h2>리뷰와 저장된 기록</h2><p>리뷰 결과를 비교하고, 이전 질문별 대화를 이어서 연습할 수 있습니다.</p></div></div>
    <nav className="library-tabs" aria-label="저장 기록 메뉴">{tabs.map(([id, label]) => <button type="button" key={id} aria-pressed={tab === id} disabled={busy} onClick={() => { setItems([]); setTrashPersonas([]); setTab(id); setReview(null); setError('') }}>{label}</button>)}</nav>
    {error && <p role="alert" className="form-error">{error}</p>}
    {busy && <LoadingProgress label="저장 기록 처리 중" expected="목록 조회·복원은 보통 1~15초, AI 리뷰 생성은 최대 수 분" slowAfterMs={120000} />}

    {tab === 'reviews' && <div className="review-workspace">
      <aside className="review-sidebar">
        <form className="review-create" onSubmit={(e) => { e.preventDefault(); action(async () => setReview(await api.createReview(agent, documentId, token, model)), true) }}>
          <div><h3>새 자료 리뷰</h3><p>질문자의 관점으로 발표 자료를 검토합니다.</p></div>
          <label>질문자<select value={agent} onChange={(e) => setAgent(e.target.value)} required><option value="">질문자 선택</option>{personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          <label>발표 자료<select value={documentId} onChange={(e) => setDocumentId(e.target.value)} required><option value="">자료 선택</option>{documents.filter((d) => d.text_length || d.full_text?.length).map((d) => <option key={d.document_id} value={d.document_id}>{d.filename}</option>)}</select></label>
          <button className="primary-btn" disabled={busy || !agent || !documentId}>리뷰 생성</button>
        </form>
        <div className="review-history"><div className="library-subheading"><h3>저장된 리뷰</h3><span>{items.length}개</span></div>{items.length > 0 && <ul>{items.map((r) => <li key={r.review_id}><button type="button" className={review?.review_id === r.review_id ? 'active' : ''} disabled={busy} onClick={() => action(async () => setReview(await api.getReview(r.review_id, token)))}><strong title={documentName(r.document_id)}>{documentName(r.document_id)}</strong><span title={personaName(r.agent_id)}>{personaName(r.agent_id)}</span><small>{r.created_at ? new Date(r.created_at).toLocaleString() : '저장된 리뷰'}</small></button></li>)}</ul>}</div>
      </aside>
      <div className="review-detail" aria-live="polite">
        {!review && <div className="library-placeholder"><strong>검토할 리뷰를 선택하세요</strong><p>왼쪽 목록에서 기존 리뷰를 열거나 새 리뷰를 생성할 수 있습니다.</p></div>}
        {review && <article>
          <header><div><span className="eyebrow">REVIEW RESULT</span><h3>{documentName(review.document_id)}</h3><p>{personaName(review.agent_id)} 관점의 평가</p></div><button type="button" className="text-btn" onClick={() => setReview(null)}>닫기</button></header>
          <CoverageNotice coverage={review.coverage} />
          <p className="grounding-note">{review.feedback?.source_check_performed ? '인용문·파일·구간의 원문 일치를 검사했습니다.' : '이전 결과: 인용 검증 정보가 없습니다. 다시 생성해주세요.'} 외부 사실 검증은 수행하지 않았으며, 인용 일치가 판단의 정확성을 보장하지는 않습니다.</p>
          {review.feedback?.verification_warnings?.map((warning) => <p className="grounding-note" key={warning}>{warning}</p>)}
          <div className="feedback-grid"><section><h4>좋은 점</h4><p>{review.feedback?.positive || '기록 없음'}</p><Evidence sources={review.feedback?.positive_sources} /></section><section><h4>보완할 점</h4><p>{review.feedback?.negative || '기록 없음'}</p><Evidence sources={review.feedback?.negative_sources} /></section></div>
          {review.claims?.length > 0 && <section className="review-section"><h4>근거 검토</h4>{review.claims.map((claim, i) => <details key={i} className="review-claim"><summary><span>{claim.claim}</span><em data-verdict={claim.verdict}>{VERDICT_LABELS[claim.verdict] || claim.verdict}</em></summary><Evidence sources={claim.sources} /></details>)}</section>}
          {review.questions?.length > 0 && <section className="review-section"><h4>예상 질문</h4><ol className="review-questions">{review.questions.map((question, i) => <li key={i}>{question}</li>)}</ol></section>}
        </article>}
      </div>
    </div>}

    {tab === 'sessions' && <div className="library-card-list">{items.map((s) => <article key={s.session_id}><div><strong title={s.persona_names.join(', ')}>{s.persona_names.join(', ') || '질문자 정보 없음'}</strong><small>{new Date(s.created_at).toLocaleString()} · 예상 질문 연습</small></div><button type="button" disabled={busy} onClick={() => action(() => resume(s.session_id))}>연습 이어 하기</button></article>)}</div>}

    {tab === 'chats' && <div className="conversation-history">{chatGroups.map((group) => {
      const first = group.messages[0]
      const preview = chatPromptPreview(first.message)
      return <article key={group.conversationId || first.message_id}>
        <header><div><strong>{personaName(group.agentId)}</strong><small>{new Date(group.latestAt).toLocaleString()} · 대화 {group.messages.length}회</small></div><button type="button" className="primary-btn" disabled={busy || !group.conversationId} onClick={() => action(() => openConversation(group))}>{group.conversationId ? '대화 열기' : '열기 불가'}</button></header>
        {preview.question && <p className="conversation-question"><b>예상 질문</b>{preview.question}</p>}
        <details><summary>저장된 대화 내용 보기</summary>{group.messages.map((chat) => { const text = chatPromptPreview(chat.message); return <div className="history-turn" key={chat.message_id}><p><b>발표자</b>{text.answer}</p><p><b>질문자</b>{chat.answer}</p><Evidence sources={chat.sources} />{chat.grounding && <small>{!chat.grounding.checked ? '근거 검증 미완료' : `근거 점수 ${Math.round(chat.grounding.score * 100)}%`}</small>}<button type="button" className="danger-action" disabled={busy} onClick={() => action(() => api.trashChat(chat.message_id, token), true)}>휴지통으로</button></div>})}</details>
      </article>
    })}</div>}

    {tab === 'trash' && <div className="trash-sections">
      <section><h3>삭제한 대화</h3>{items.map((c) => <article key={c.message_id}><p>{chatPromptPreview(c.message).answer}</p><small>{new Date(c.created_at).toLocaleString()}</small><div><button disabled={busy} onClick={() => action(() => api.restoreChat(c.message_id, token), true)}>대화 복원</button><button className="danger-action" disabled={busy} onClick={() => permanent(() => api.permanentlyDeleteChat(c.message_id, token))}>완전 삭제</button></div></article>)}</section>
      <section><h3>삭제한 질문자</h3>{trashPersonas.map((p) => <article key={p.agent_id}><strong>{p.name}</strong><div><button disabled={busy} onClick={() => action(() => api.restoreAgent(p.agent_id, token), true)}>질문자 복원</button><button className="danger-action" disabled={busy} onClick={() => permanent(() => api.permanentlyDeleteAgent(p.agent_id, token))}>완전 삭제</button></div></article>)}</section>
    </div>}
    {isEmpty && <p className="library-placeholder">이 탭에 저장된 기록이 없습니다.</p>}
  </section>
}
