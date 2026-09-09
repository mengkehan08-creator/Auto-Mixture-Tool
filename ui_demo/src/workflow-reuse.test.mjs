import test from 'node:test'
import assert from 'node:assert/strict'
import { canRestart } from './workflow-state.js'

test('restart options require confirmed successful predecessors and a terminal source', () => {
  const workflow = { pipeline_version: 3, status: 'FAILED', jobs: [
    { status: 'SUCCEEDED' }, { status: 'FAILED' }, { status: 'WAITING' },
  ] }
  assert.equal(canRestart(workflow, 'training'), true)
  assert.equal(canRestart(workflow, 'evaluation'), false)
  workflow.jobs[1].status = 'SUCCEEDED'
  assert.equal(canRestart(workflow, 'evaluation'), true)
  for (const status of ['TRAINING_RUNNING', 'NEEDS_ATTENTION', 'WAITING_AUTH', 'DELETING']) {
    assert.equal(canRestart({ ...workflow, status }, 'evaluation'), false)
  }
  assert.equal(canRestart({ ...workflow, delete_requested: true }, 'training'), false)
  assert.equal(canRestart({ ...workflow, pipeline_version: 2 }, 'evaluation'), false)
})
