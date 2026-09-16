import React, { useEffect, useState } from 'react'
import * as api from './api'
import LoadingProgress from './LoadingProgress'

export function CoverageNotice({ coverage }) {
  if (!coverage) return <small>분석 범위 정보 없음</small>
  return <p className="grounding-note">{coverage.truncated ? '일부 구간 분석' : '전체 구간 분석'} · {coverage.analyzed_chunks}/{coverage.total_chunks}개 구간</p>
}

function Evidence({ sources = [] }) {
  return <ul>{sources.map((s, i) => <li key={i}>{s.filename}{s.page ? ` · ${s.page}쪽/슬라이드` : ''}{s.excerpt && <blockquote>{s.excerpt}</blockquote>}</li>)}</ul>
}

export default function WorkspaceLibrary({ token, documents, personas, onResume, onChanged }) {
  const [tab, setTab] = useState('reviews')
  const [items, setItems] = useState([])
  const [trashPersonas, setTrashPersonas] = useState([])
  const [review, setReview] = useState(null)
  const [agent, setAgent] = useState('')
  const [document, setDocument] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
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
    try { await work(); if (changed) await onChanged(); setRevision((n) => n + 1) }
    catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  async function resume(id) {
    const [session, chats] = await Promise.all([api.getPracticeSession(id, token), api.listChats(token)])
    onResume(session, chats)
  }
  function permanent(work) {
    if (window.confirm('완전히 삭제하면 복구할 수 없습니다. 삭제하시겠습니까?')) action(work, true)
  }
  return <section className="source-block workspace-library">
    <h2>리뷰와 저장된 기록</h2>
    <nav aria-label="저장 기록 메뉴">{[['reviews', '자료 리뷰'], ['sessions', '연습 기록'], ['chats', '대화 이력'], ['trash', '휴지통']].map(([id, label]) => <button key={id} aria-pressed={tab === id} disabled={busy} onClick={() => { setItems([]); setTrashPersonas([]); setTab(id); setReview(null) }}>{label}</button>)}</nav>
    {error && <p role="alert" className="form-error">{error}</p>}
    {busy && <LoadingProgress label="저장 기록 처리 중" expected="목록 조회·복원은 보통 1~15초, AI 리뷰 생성은 최대 수 분" slowAfterMs={120000} />}
    {tab === 'reviews' && <>
      <form onSubmit={(e) => { e.preventDefault(); action(async () => setReview(await api.createReview(agent, document, token))) }}>
        <label>질문자 <select value={agent} onChange={(e) => setAgent(e.target.value)} required><option value="">선택</option>{personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label>발표 자료 <select value={document} onChange={(e) => setDocument(e.target.value)} required><option value="">선택</option>{documents.filter((d) => d.text_length || d.full_text?.length).map((d) => <option key={d.document_id} value={d.document_id}>{d.filename}</option>)}</select></label>
        <button disabled={busy || !agent || !document}>리뷰 생성</button>
      </form>
      <ul>{items.map((r) => <li key={r.review_id}><button disabled={busy} onClick={() => action(async () => setReview(await api.getReview(r.review_id, token)))}>{documents.find((d) => d.document_id === r.document_id)?.filename || '발표 자료'} · {personas.find((p) => p.id === r.agent_id)?.name || '평가자'} 리뷰 열기</button></li>)}</ul>
      {review && <article><h3>리뷰 결과</h3><CoverageNotice coverage={review.coverage} /><p><strong>좋은 점</strong> {review.feedback.positive}</p><p><strong>보완할 점</strong> {review.feedback.negative}</p>{review.claims.map((c, i) => <div key={i}><p>{c.claim} · {{ supported: '근거 있음', partially_supported: '일부 근거 있음', contradicted: '자료와 상충', overgeneralized: '과도한 일반화', insufficient_evidence: '근거 부족', not_verifiable: '검증 불가' }[c.verdict] || c.verdict}</p><Evidence sources={c.sources} /></div>)}<ol>{review.questions.map((q, i) => <li key={i}>{q}</li>)}</ol></article>}
    </>}
    {tab === 'sessions' && <ul>{items.map((s) => <li key={s.session_id}><button disabled={busy} onClick={() => action(() => resume(s.session_id))}>{new Date(s.created_at).toLocaleString()} · {s.persona_names.join(', ')} 이어 하기</button></li>)}</ul>}
    {(tab === 'chats' || tab === 'trash') && <div>{items.map((c) => <article key={c.message_id}><p>{c.message}</p><p>{c.answer}</p><Evidence sources={c.sources} />{c.grounding && <p>{!c.grounding.checked ? '근거 검증을 완료하지 못했습니다.' : `근거 점수 ${Math.round(c.grounding.score * 100)}%`}</p>}{tab === 'chats' ? <button disabled={busy} onClick={() => action(() => api.trashChat(c.message_id, token), true)}>대화 휴지통으로</button> : <><button disabled={busy} onClick={() => action(() => api.restoreChat(c.message_id, token), true)}>대화 복원</button><button disabled={busy} onClick={() => permanent(() => api.permanentlyDeleteChat(c.message_id, token))}>대화 완전 삭제</button></>}</article>)}</div>}
    {tab === 'trash' && <div><h3>질문자 휴지통</h3>{trashPersonas.map((p) => <article key={p.agent_id}>{p.name}<button disabled={busy} onClick={() => action(() => api.restoreAgent(p.agent_id, token), true)}>질문자 복원</button><button disabled={busy} onClick={() => permanent(() => api.permanentlyDeleteAgent(p.agent_id, token))}>질문자 완전 삭제</button></article>)}</div>}
    {!busy && !items.length && <p>저장된 기록이 없습니다.</p>}
  </section>
}
