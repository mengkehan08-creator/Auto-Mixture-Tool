import test from 'node:test'
import assert from 'node:assert/strict'
import { hasProgress, submissionFailed, fieldLabels, newestWorkflows, statusView, stageIndex } from './workflow-state.js'

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

test('creation time determines order without mutating the source', () => {
  const rows = [{ id: 'z', created_at: '2026-09-07T10:00:00+08:00' },
    { id: 'a', created_at: '2026-09-08T10:00:00+08:00' }, { id: 'unknown' }]
  assert.deepEqual(newestWorkflows(rows).map(w => w.id), ['a', 'z', 'unknown'])
  assert.equal(rows[0].id, 'z')
})

test('ruler uses confirmed job status, not estimated percentage', () => {
  assert.equal(stageIndex({ status: 'MIXING_RUNNING', progress: 45, jobs: [{ id: '1', status: 'PENDING' }] }), 0)
  assert.equal(stageIndex({ status: 'MIXING_RUNNING', jobs: [{ id: '1', status: 'RUNNING' }] }), 1)
  assert.equal(stageIndex({ status: 'MIXING_SUCCEEDED' }), 2)
  assert.equal(stageIndex({ status: 'TRAINING_RUNNING', jobs: [{}, { id: '2', status: 'SUBMITTED' }] }), 2)
  assert.equal(stageIndex({ status: 'TRAINING_RUNNING', jobs: [{}, { id: '2', status: 'RUNNING' }] }), 3)
  assert.equal(stageIndex({ status: 'SUCCEEDED' }), 4)
  assert.equal(statusView('failed').tone, 'danger')
  assert.equal(statusView('RUNNING').tone, 'active')
  assert.equal(statusView('completed').tone, 'success')
  assert.equal(statusView('WAITING_AUTH').tone, 'warning')
  assert.equal(statusView('CANCELED').label, '已终止')
})
