import test from 'node:test'
import assert from 'node:assert/strict'
import { hasProgress, submissionFailed, fieldLabels, newestWorkflows, searchWorkflows, statusView, stageIndex } from './workflow-state.js'

test('only confirmed jobs without errors show progress', () => {
  assert.equal(hasProgress({ status: 'QUEUED', jobs: [{ id: null }] }), false)
  assert.equal(hasProgress({ status: 'MIXING_RUNNING', jobs: [{ id: 'job-1' }] }), true)
  for (const status of ['FAILED', 'NEEDS_ATTENTION', 'WAITING_AUTH', 'DELETING', 'DELETE_FAILED', 'DELETED']) {
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

test('name search supports partial Chinese and case-insensitive text, preserving order', () => {
  const rows = [{ name: 'QuaDMix-数学对比-20260908' }, { name: '随机配比-20260907' },
    { name: 'QuaDMix-数学对比-20260906' }, {}]
  assert.deepEqual(searchWorkflows(rows, ' 数学对比 '), [rows[0], rows[2]])
  assert.deepEqual(searchWorkflows(rows, 'quadmix'), [rows[0], rows[2]])
  assert.deepEqual(searchWorkflows(rows, '20260907'), [rows[1]])
  assert.deepEqual(searchWorkflows(rows, rows[0].name), [rows[0]])
  assert.deepEqual(searchWorkflows(rows, 'missing'), [])
  assert.deepEqual(searchWorkflows(rows, '.*'), [])
  assert.deepEqual(searchWorkflows(rows, '   '), rows)
  assert.deepEqual(searchWorkflows([], 'test'), [])
})

test('ruler uses confirmed job status, not estimated percentage', () => {
  assert.equal(stageIndex({ status: 'MIXING_RUNNING', progress: 45, jobs: [{ id: '1', status: 'PENDING' }] }), 0)
  assert.equal(stageIndex({ status: 'MIXING_RUNNING', jobs: [{ id: '1', status: 'RUNNING' }] }), 1)
  assert.equal(stageIndex({ status: 'MIXING_SUCCEEDED' }), 2)
  assert.equal(stageIndex({ status: 'TRAINING_RUNNING', jobs: [{}, { id: '2', status: 'SUBMITTED' }] }), 2)
  assert.equal(stageIndex({ status: 'TRAINING_RUNNING', jobs: [{}, { id: '2', status: 'RUNNING' }] }), 3)
  assert.equal(stageIndex({ status: 'SUCCEEDED' }), 6)
  assert.equal(stageIndex({ status: 'EVALUATION_RUNNING', jobs: [{}, {}, { id: '3', status: 'RUNNING' }] }), 5)
  assert.equal(statusView('failed').tone, 'danger')
  assert.equal(statusView('RUNNING').tone, 'active')
  assert.equal(statusView('completed').tone, 'success')
  assert.equal(statusView('WAITING_AUTH').tone, 'warning')
  assert.equal(statusView('CANCELED').label, '已终止')
  assert.equal(statusView('DELETING').label, '正在终止并删除')
  assert.equal(statusView('DELETE_FAILED').label, '删除未完成')
})
