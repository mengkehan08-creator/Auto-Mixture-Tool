import test from 'node:test'
import assert from 'node:assert/strict'
import { draftKey, readDraft, serializeDraft, writeDraft } from './experiment-draft.js'
import { createEvaluationConfig, createRuntimeConfig, createStrategy, createTrainingConfig } from './data/defaults.js'
import { initializeJobCommands, refreshJobCommands } from './job-commands.js'

const state = () => ({ step: 2, runtime: createRuntimeConfig(), training: createTrainingConfig(),
  evaluation: createEvaluationConfig(), strategies: [createStrategy(), createStrategy('manual')] })
const storage = () => {
  const values = new Map()
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
}

test('refresh restores topology, fixed batch, packages and custom edits without credentials or stale checks', () => {
  const current = state(), saved = storage()
  current.training.nodes = 3; current.training.batchSizeMode = 'fixed'; current.training.totalBatchSize = 1081344
  current.runtime.experimentName = 'three-node draft'
  current.runtime.modelarts.authorization = 'private-authorization'
  current.runtime.datasetEstimate = { ready: true, check_id: 'stale-check' }
  current.runtime.request_id = 'old-request'
  current.evaluation.api.key = 'private-api-key'
  current.evaluation.obsPackages = [{ name: 'extra', obs_uri: 'obs://bucket/eval/' }]
  current.strategies[1].scriptConfig = { token: 'private-script-token', max_tokens: 128, limit: 12 }
  current.strategies[0].trainingNodesOverride = 4
  const serialized = serializeDraft(current)
  writeDraft(saved, serialized)
  assert.doesNotMatch(serialized, /private-authorization|private-api-key|private-script-token|stale-check|old-request/)
  assert.equal(current.runtime.modelarts.authorization, 'private-authorization')
  const restored = readDraft(saved)
  assert.equal(restored.step, 2)
  assert.equal(restored.training.nodes, 3)
  assert.equal(restored.training.totalBatchSize, 1081344)
  assert.equal(restored.training.batchSizeMode, 'fixed')
  assert.equal(restored.runtime.experimentName, 'three-node draft')
  assert.equal(restored.runtime.modelarts.authorization, '')
  assert.equal(restored.evaluation.api.key, '')
  assert.equal(restored.runtime.datasetEstimate, null)
  assert.deepEqual(restored.evaluation.obsPackages, current.evaluation.obsPackages)
  assert.equal(restored.strategies[0].trainingNodesOverride, 4)
  assert.deepEqual(restored.strategies[1].scriptConfig, { max_tokens: 128, limit: 12 })
  const newStrategy = createStrategy()
  assert.ok(!restored.strategies.some(item => item.id === newStrategy.id))
  saved.removeItem(draftKey)
  assert.equal(readDraft(saved), null)
})

test('restored automatic commands still follow changes while manual edits remain manual', () => {
  const current = state(), saved = storage()
  const defaults = { mixing: 'old mix', training: 'old train', evaluation: 'old eval' }
  initializeJobCommands(current.strategies, current.runtime, defaults)
  current.strategies[1].trainingCommand = 'custom train'
  writeDraft(saved, serializeDraft(current))
  const restored = readDraft(saved)
  initializeJobCommands(restored.strategies, restored.runtime, defaults)
  refreshJobCommands(restored.strategies, restored.runtime, { mixing: 'next mix', training: 'next train', evaluation: 'next eval' })
  assert.equal(restored.strategies[0].trainingCommand, 'next train')
  assert.equal(restored.strategies[1].trainingCommand, 'custom train')
})

test('every draft within the size limit can restore all of its strategies', () => {
  const current = state(), saved = storage()
  current.strategies = Array.from({ length: 1001 }, () => createStrategy('random'))
  writeDraft(saved, serializeDraft(current))
  assert.equal(readDraft(saved).strategies.length, 1001)
})

test('malformed, incompatible or oversized drafts are rejected and storage failures reach the UI', () => {
  const saved = storage()
  assert.equal(readDraft(saved), null)
  assert.equal(readDraft(null), null)
  for (const value of ['{broken', JSON.stringify({ version: 0 }), JSON.stringify({ ...state(), version: 1, strategies: [] })]) {
    saved.setItem(draftKey, value)
    assert.throws(() => readDraft(saved))
  }
  assert.throws(() => writeDraft(saved, 'x'.repeat(1024 * 1024 + 1)), /1 MiB/)
  assert.throws(() => writeDraft(saved, '中'.repeat(400000)), /1 MiB/)
  saved.setItem(draftKey, 'x'.repeat(1024 * 1024 + 1))
  assert.throws(() => readDraft(saved), /过大/)
  assert.throws(() => writeDraft({ setItem() { throw new Error('quota exceeded') } }, serializeDraft(state())), /quota/)
})
