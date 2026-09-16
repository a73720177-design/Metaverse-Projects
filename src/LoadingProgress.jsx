import React, { useEffect, useState } from 'react'
import { formatWaitTime } from './loading-progress-utils.mjs'

export default function LoadingProgress({
  label = '처리 중',
  expected = '작업량과 장비 성능에 따라 달라질 수 있습니다.',
  elapsedMs,
  compact = false,
  slowAfterMs = 120000,
}) {
  const [startedAt] = useState(() => performance.now())
  const [now, setNow] = useState(startedAt)
  useEffect(() => {
    if (elapsedMs != null) return undefined
    const timer = setInterval(() => setNow(performance.now()), 250)
    return () => clearInterval(timer)
  }, [elapsedMs])
  const elapsed = elapsedMs ?? now - startedAt
  return <span className={`wait-progress ${compact ? 'compact' : ''}`} role="status" aria-live="polite">
    <span className="wait-progress-heading"><strong>{label}</strong><span>경과 {formatWaitTime(elapsed)}</span></span>
    <span className="wait-progress-track" aria-hidden="true"><span /></span>
    <small>{expected}{elapsed >= slowAfterMs ? ' · 예상보다 오래 걸리고 있지만 계속 처리 중입니다.' : ''}</small>
  </span>
}
