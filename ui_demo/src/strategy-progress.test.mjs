import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { strategyProgress } from './strategy-progress.js'

function workflow(count = 3, evaluation = true) {
  return { pipeline_version: 4, status: 'RUNNING', jobs: [
    ...Array.from({ length: count }, (_, i) => ['mixing', 'training'].map(module => ({
      strategy_id: `s${i}`, strategy_name: `策略 ${i}`, module, status: 'PENDING', id: null,
    }))).flat(), ...(evaluation ? [{ module: 'evaluation', status: 'PENDING', id: null }] : []),
  ] }
}
const finish = job => Object.assign(job, { id: 'remote-id', status: 'SUCCEEDED' })

test('groups by strategy ID, not name or job order, with one evaluation tail', () => {
  const w = workflow()
  w.jobs[2].strategy_name = w.jobs[0].strategy_name
  w.jobs.reverse()
  const graph = strategyProgress(w)
  assert.equal(graph.branches.length, 3)
  assert.ok(graph.branches.every(b => b.points.length === 4))
  assert.deepEqual(graph.tail.map(p => p.label), ['训练汇合', '评测提交', '模型评测', '全部完成'])
  assert.ok(graph.branches.every(b => b.points.every(p => p.state === 'waiting')))
})

test('concurrent mixing and training do not prematurely complete the merge', () => {
  const w = workflow()
  finish(w.jobs[0])
  Object.assign(w.jobs[1], { id: 'train-0', status: 'RUNNING' })
  Object.assign(w.jobs[2], { id: 'mix-1', status: 'RUNNING' })
  const graph = strategyProgress(w)
  assert.equal(graph.branches[0].points[3].state, 'running')
  assert.equal(graph.branches[1].points[1].state, 'running')
  assert.equal(graph.tail[0].state, 'waiting')
  assert.equal(graph.tail[1].detail, '等待全部训练')
})

test('completed and reused branches merge, then evaluation can run', () => {
  const w = workflow()
  w.jobs.slice(0, 6).forEach(job => Object.assign(job, { reused: true, status: 'SUCCEEDED' }))
  Object.assign(w.jobs[6], { id: 'eval', status: 'RUNNING' })
  let graph = strategyProgress(w)
  assert.equal(graph.completed, 3)
  assert.equal(graph.branches[0].points[1].detail, '已复用')
  assert.equal(graph.tail[0].state, 'done')
  assert.equal(graph.tail[2].state, 'running')
  finish(w.jobs[6]); w.status = 'SUCCEEDED'
  graph = strategyProgress(w)
  assert.equal(graph.finished, true)
  assert.ok(graph.tail.every(p => p.state === 'done'))
})

test('failure, queueing and missing confirmation do not masquerade as running or completion', () => {
  const w = workflow()
  Object.assign(w.jobs[0], { id: 'queue', status: 'QUEUED' })
  Object.assign(w.jobs[2], { id: 'failure', status: 'FAILED' })
  w.jobs[3].status = 'BLOCKED'
  w.jobs[4].status = 'NEEDS_ATTENTION'
  const graph = strategyProgress(w)
  assert.equal(graph.branches[0].points[1].detail, '排队中')
  assert.equal(graph.branches[1].points[1].state, 'error')
  assert.equal(graph.branches[2].points[0].state, 'blocked')
  assert.equal(graph.tail[0].state, 'blocked')
  assert.equal(graph.completed, 0)
})

test('no evaluation, single/many branches, unavailable state and zero jobs are supported', () => {
  for (const count of [1, 16, 32]) {
    const w = workflow(count, false)
    w.jobs.forEach(finish); w.status = 'SUCCEEDED'
    const graph = strategyProgress(w)
    assert.equal(graph.branches.length, count)
    assert.deepEqual(graph.tail.map(p => p.label), ['训练汇合', '全部完成'])
    assert.equal(graph.finished, true)
    w.statusUnavailable = true
    const unavailable = strategyProgress(w)
    assert.equal(unavailable.finished, false)
    assert.equal(unavailable.completed, 0)
    assert.ok(unavailable.branches.every(b => b.points.every(p => p.state === 'waiting')))
  }
  assert.equal(strategyProgress({ jobs: [] }).finished, false)
})

test('progress view uses a connected strategy diagram instead of per-job progress bars', () => {
  const ui = readFileSync(new URL('./components/WorkflowProgress.vue', import.meta.url), 'utf8')
  assert.match(ui, /<StrategyProgress/)
  assert.doesNotMatch(ui, /<progress\b|parallel-progress|独立作业进度/)
})
