import React, { Component, useEffect, useState, useSyncExternalStore } from 'react'
import { clearErrors, diagnosticText, getErrors, reportError, reportLocalError, subscribeErrors } from './api-errors.mjs'
import { getDeveloperFeatureStatus, getServiceStatus } from './api'
import './errors.css'

function ErrorDetails({ error }) {
  const [copyStatus, setCopyStatus] = useState('')
  async function copy() {
    try {
      await navigator.clipboard.writeText(diagnosticText(error))
      setCopyStatus('복사했습니다.')
    } catch { setCopyStatus('자동 복사가 불가능합니다. 아래 내용을 선택해 복사해주세요.') }
  }
  return <article className="error-record">
    <p className="error-message">{error.message}</p>
    <p className="error-hint">{error.hint}</p>
    {error.retryAfter !== null && <p>응답 시점 기준 {error.retryAfter}초 후 다시 시도해주세요.</p>}
    {error.fields.length > 0 && <ul className="error-fields">{error.fields.map((field, index) => <li key={index}><strong>{field.label || '입력값'}</strong>: {field.message}</li>)}</ul>}
    <details>
      <summary>개발 확인용 상세 정보 · {error.code}</summary>
      <dl className="error-metadata">
        <dt>발생 시각</dt><dd>{new Date(error.time).toLocaleString('ko-KR')}</dd>
        <dt>오류 코드</dt><dd>{error.code}</dd>
        <dt>HTTP 상태</dt><dd>{error.status ?? '응답 상태 없음'}</dd>
        <dt>요청</dt><dd>{error.path ? `${error.method} ${error.path}` : '브라우저 내부 처리'}</dd>
        <dt>요청 ID</dt><dd>{error.requestId || '서버에서 제공하지 않음'}</dd>
        {error.errorType && <><dt>예외 종류</dt><dd>{error.errorType}</dd></>}
      </dl>
      <button type="button" onClick={copy}>오류 정보 복사</button>
      <p role="status">{copyStatus}</p>
      {copyStatus.startsWith('자동') && <textarea readOnly aria-label="복사할 오류 정보" value={diagnosticText(error)} rows={8} />}
    </details>
  </article>
}

export function ErrorCenter() {
  const errors = useSyncExternalStore(subscribeErrors, getErrors, getErrors)
  const [open, setOpen] = useState(false)
  const [checking, setChecking] = useState(false)
  const [services, setServices] = useState(null)
  const [features, setFeatures] = useState(null)
  const [activeTab, setActiveTab] = useState('connections')
  useEffect(() => { if (errors.length) setOpen(true) }, [errors])
  useEffect(() => {
    const rejection = (event) => reportError(event.reason)
    const runtime = (event) => { if (event.error) reportError(event.error) }
    const invalid = (event) => {
      const input = event.target
      const label = input.labels?.[0]?.textContent || input.name || '입력값'
      reportLocalError(`${label}: ${input.validationMessage || '입력값을 확인해주세요.'}`)
    }
    window.addEventListener('unhandledrejection', rejection)
    window.addEventListener('error', runtime)
    document.addEventListener('invalid', invalid, true)
    return () => {
      window.removeEventListener('unhandledrejection', rejection)
      window.removeEventListener('error', runtime)
      document.removeEventListener('invalid', invalid, true)
    }
  }, [])
  async function checkServices() {
    if (checking) return
    setChecking(true)
    try {
      if (activeTab === 'features') setFeatures(await getDeveloperFeatureStatus())
      else setServices(await getServiceStatus())
    } catch { /* Common API boundary reports it. */ }
    finally { setChecking(false) }
  }
  function featureState(feature) {
    if (feature.enabled === false) return { label: 'OFF', className: 'is-off' }
    if (feature.enabled !== true) return { label: '설정 미확인', className: 'is-unknown' }
    if (feature.operational === true) return { label: 'ON · 정상', className: 'is-on' }
    if (feature.operational === false) return { label: 'ON · 오류', className: 'is-error' }
    return { label: 'ON · 미확인', className: 'is-unknown' }
  }
  function featureDetail(feature) {
    const details = []
    if (feature.model) details.push(`모델 ${feature.model}`)
    if (feature.mode) details.push(`모드 ${feature.mode}`)
    if (feature.workers) details.push(`동시 작업 ${feature.workers}개`)
    if (typeof feature.gpu_percent === 'number') details.push(`VRAM 오프로딩 ${feature.gpu_percent}%`)
    if (feature.models && Object.keys(feature.models).length) {
      details.push([...new Set(Object.values(feature.models))].join(', '))
    }
    return details.join(' · ') || '추가 설정 정보 없음'
  }
  return <aside className="error-center" aria-label="오류 및 서비스 상태">
    <button className={`error-center-toggle ${errors.length ? 'has-errors' : ''}`} type="button" aria-expanded={open} aria-controls="error-center-panel" onClick={() => setOpen((value) => !value)}>오류 · 상태 {errors.length > 0 && <span>{errors.length}</span>}</button>
    {open && <section id="error-center-panel" className="error-center-panel">
      <header><h2>오류 및 서비스 상태</h2><button type="button" onClick={() => setOpen(false)} aria-label="오류 패널 접기">접기</button></header>
      <div className="error-center-tabs" role="tablist" aria-label="상태 정보 분류">
        <button type="button" role="tab" aria-selected={activeTab === 'connections'} onClick={() => setActiveTab('connections')}>연결 상태</button>
        <button type="button" role="tab" aria-selected={activeTab === 'features'} onClick={() => setActiveTab('features')}>개발자 기능</button>
        <button type="button" role="tab" aria-selected={activeTab === 'errors'} onClick={() => setActiveTab('errors')}>오류 기록 {errors.length > 0 && `(${errors.length})`}</button>
      </div>
      {activeTab !== 'errors' && <div className="error-center-actions"><button type="button" disabled={checking} onClick={checkServices}>{checking ? '확인 중…' : '현재 상태 새로고침'}</button></div>}
      {activeTab === 'connections' && <>
        {!services && <p className="status-guide">현재 Backend·DB·LLM 연결을 확인하려면 새로고침을 눌러주세요.</p>}
        {services && <div className="service-check" role="status"><strong>{services.status === 'ok' ? '서비스 연결 확인 완료' : '일부 서비스를 확인해주세요'}</strong>{Object.entries(services.services || {}).map(([key, value]) => <div key={key}><b>{value.label || key}: {value.status}</b><p>{value.message}</p>{value.contract?.missing && Object.keys(value.contract.missing).length > 0 && <p>누락 항목: {Object.entries(value.contract.missing).map(([table, columns]) => `${table}: ${Array.isArray(columns) ? columns.join(', ') : String(columns)}`).join(' / ')}</p>}</div>)}</div>}
      </>}
      {activeTab === 'features' && <>
        {!features && <p className="status-guide">vLLM, Ollama, 임베딩, RAG, DB 등 실제 런타임 기능의 ON/OFF 상태를 확인할 수 있습니다.</p>}
        {features && <div className="feature-status" role="status">
          <p className="feature-summary"><strong>활성 LLM 제공자</strong><span>{features.active_llm_provider}</span></p>
          <p className="feature-summary"><strong>선택 가능한 모델</strong><span>{(features.models || []).filter((model) => model.available).map((model) => model.id).join(', ') || '없음'}</span></p>
          <div className="feature-grid">{Object.entries(features.features || {}).map(([key, feature]) => {
            const state = featureState(feature)
            return <article className="feature-card" key={key}>
              <div><strong>{feature.label || key}</strong><span className={`feature-badge ${state.className}`}>{state.label}</span></div>
              <p>{featureDetail(feature)}</p>
            </article>
          })}</div>
          <p className="feature-note">OFF는 현재 설정에서 사용하지 않는 기능입니다. ON · 오류는 켜져 있지만 실제 연결 또는 필수 모델 확인에 실패한 상태입니다.</p>
        </div>}
      </>}
      {activeTab === 'errors' && <>
        <div className="error-center-actions"><button type="button" disabled={!errors.length} onClick={clearErrors}>기록 지우기</button></div>
        {errors[0] && <p className="error-live" role="alert">{errors[0].message}</p>}
        {!errors.length ? <p className="error-empty">이 화면에서 기록된 오류가 없습니다.</p> : errors.map((error) => <ErrorDetails key={error.id} error={error} />)}
        <footer>최근 오류 최대 20개를 이 탭에서만 보관합니다. 요청 본문·비밀번호·인증 토큰은 기록하지 않습니다.</footer>
      </>}
    </section>}
  </aside>
}

export class AppErrorBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error) { reportError(error) }
  render() {
    if (!this.state.failed) return this.props.children
    return <main className="center-screen"><section className="auth-card" role="alert"><h1>화면을 표시하지 못했습니다.</h1><p>오류 패널에서 상세 정보를 확인한 뒤 다시 시도해주세요.</p><button type="button" onClick={() => window.location.reload()}>화면 새로고침</button></section></main>
  }
}
