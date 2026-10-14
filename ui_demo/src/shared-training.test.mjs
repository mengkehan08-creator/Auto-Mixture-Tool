import test from 'node:test'
import assert from 'node:assert/strict'
import { createStrategy, createTrainingConfig, trainingParameters } from './data/defaults.js'
import { syncSharedTraining } from './shared-training.js'
import { batchExample, planQuadMixBatch, materializeQuadMixBatch } from './quadmix-batch.js'
import { copyWorkflow } from './copy-workflow.js'

test('shared nodes and priority propagate, batch override survives and can be cleared', () => {
  const training = createTrainingConfig()
  const source = createStrategy()
  const batch = materializeQuadMixBatch(source, planQuadMixBatch(source, {
    ...batchExample(), experiments: '50', values: '.2', trainingNodes: 4, overrideTrainingNodes: true,
  }))
  const strategies = [source, createStrategy('manual'), ...batch]
  source.trainingJobName = 'old-training-name'
  source.modelName = 'old-model'
  source.trainingCommand = 'custom command'
  training.nodes = 3; training.priority = 1
  syncSharedTraining(strategies, training)
  assert.deepEqual(strategies.map(s => s.trainingNodes), [3, 3, 4])
  assert.ok(strategies.every(s => s.trainingPriority === 1 && s.trainingJobName === '' && s.modelName === ''))
  assert.equal(source.trainingCommand, 'custom command')
  training.nodes = 8
  syncSharedTraining(strategies, training)
  assert.deepEqual(strategies.map(s => s.trainingNodes), [8, 8, 4])
  batch[0].trainingNodesOverride = null
  syncSharedTraining(strategies, training)
  assert.deepEqual(strategies.map(s => s.trainingNodes), [8, 8, 8])
})

test('default batch follows future shared-node edits and replacements inherit scheduling', () => {
  const source = createStrategy()
  const training = { ...createTrainingConfig(), nodes: 5, priority: 3 }
  const batch = materializeQuadMixBatch(source, planQuadMixBatch(source, { ...batchExample(), defaultTrainingNodes: 5 }))
  assert.ok(batch.every(s => s.trainingNodesOverride === null && s.trainingNodes === 5))
  training.nodes = 7
  syncSharedTraining(batch, training)
  assert.ok(batch.every(s => s.trainingNodes === 7 && s.trainingPriority === 3))
  batch[0] = createStrategy('random')
  syncSharedTraining(batch, training)
  assert.equal(batch[0].trainingNodes, 7)
})

test('copying restores the common priority and preserves differing historical node settings', () => {
  const draft = copyWorkflow({ training_nodes: 2, training: {}, resources: {}, evaluation: { datasets: [] },
    strategies: [{ type: 'quadmix', training_nodes: 4, training_priority: 1 }, { type: 'random', training_nodes: 2, training_priority: 1 }] })
  assert.equal(draft.training.priority, 1)
  draft.training.nodes = 3
  syncSharedTraining(draft.strategies, draft.training)
  assert.deepEqual(draft.strategies.map(s => s.trainingNodes), [4, 3])
})

test('global batch is optional, shared by strategies and restored when copying', () => {
  const config = createTrainingConfig()
  assert.equal(trainingParameters(config).total_batch_size, undefined)
  config.totalBatchSize = 540672
  const strategies = [createStrategy(), createStrategy('random')]
  syncSharedTraining(strategies, config)
  assert.ok(strategies.every(s => s.trainingOverrides.total_batch_size === 540672))
  const copy = copyWorkflow({ training: { total_batch_size: 540672 }, resources: {}, strategies: [], evaluation: { datasets: [] } })
  assert.equal(copy.training.totalBatchSize, 540672)
  config.totalBatchSize = ''
  assert.equal(trainingParameters(config).total_batch_size, undefined)
})
