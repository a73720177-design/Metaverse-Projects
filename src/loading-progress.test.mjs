import test from 'node:test'
import assert from 'node:assert/strict'
import { formatWaitTime } from './loading-progress-utils.mjs'

test('wait duration is understandable in seconds and minutes', () => {
  assert.equal(formatWaitTime(999), '0초')
  assert.equal(formatWaitTime(12_500), '12초')
  assert.equal(formatWaitTime(125_000), '2분 5초')
})
