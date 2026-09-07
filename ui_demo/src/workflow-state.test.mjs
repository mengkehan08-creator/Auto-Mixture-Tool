import test from 'node:test'
import assert from 'node:assert/strict'
import { hasProgress, submissionFailed, fieldLabels } from './workflow-state.js'

test('only confirmed jobs without errors show progress', () => {
  assert.equal(hasProgress({ status: 'QUEUED', jobs: [{ id: null }] }), false)
  assert.equal(hasProgress({ status: 'MIXING_RUNNING', jobs: [{ id: 'job-1' }] }), true)
  for (const status of ['FAILED', 'NEEDS_ATTENTION', 'WAITING_AUTH']) {
    assert.equal(hasProgress({ status, jobs: [{ id: 'job-1' }] }), false)
  }
  assert.equal(hasProgress({ status: 'MIXING_RUNNING', message: '查询失败', jobs: [{ id: 'job-1' }] }), false)
  assert.equal(submissionFailed({ status: 'FAILED' }), true)
  assert.equal(fieldLabels.Authorization, 'Authorization')
  assert.equal(fieldLabels.pool_id, 'pool_id')
})
