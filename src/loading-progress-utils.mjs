export function formatWaitTime(milliseconds = 0) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return minutes ? `${minutes}분 ${remainder}초` : `${remainder}초`
}
