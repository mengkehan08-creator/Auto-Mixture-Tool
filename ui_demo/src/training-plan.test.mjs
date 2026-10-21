import test from 'node:test'
import assert from 'node:assert/strict'
import { trainingNodeCounts, batchSizeMode } from './training-plan.js'
import { createTrainingConfig, trainingParameters } from './data/defaults.js'
import { copyWorkflow } from './copy-workflow.js'

test('node planning follows shared edits and preserves explicit batch node overrides', () => {
  const training = { nodes: 3 }
  const strategies = [{ trainingNodes: 2 }, { trainingNodesOverride: 4 }, { trainingNodesOverride: 3 }]
  assert.deepEqual(trainingNodeCounts(strategies, training), [3, 4])
  training.nodes = 2
  assert.deepEqual(trainingNodeCounts(strategies, training), [2, 3, 4])
  assert.deepEqual(trainingNodeCounts([], training), [2])
})

test('automatic mode never submits a stale manual value; manual mode preserves invalid input for validation', () => {
  const training = createTrainingConfig()
  training.totalBatchSize = 1048576
  assert.equal(trainingParameters(training).total_batch_size, undefined)
  training.batchSizeMode = 'fixed'
  assert.equal(trainingParameters(training).total_batch_size, 1048576)
  training.totalBatchSize = ''
  assert.equal(trainingParameters(training).total_batch_size, '')
})

test('historical explicit batches stay fixed and saved automatic jobs remain automatic on copy', () => {
  assert.equal(batchSizeMode({}), 'auto')
  assert.equal(batchSizeMode({ total_batch_size: 1081344 }), 'fixed')
  assert.equal(batchSizeMode({ batch_size_mode: 'auto', total_batch_size: 1081344 }), 'auto')
  const copied = copyWorkflow({ training_nodes: 3, resources: {}, strategies: [], evaluation: { datasets: [] },
    training: { batch_size_mode: 'auto', total_batch_size: 1081344 } })
  assert.equal(copied.training.batchSizeMode, 'auto')
  assert.equal(trainingParameters(copied.training).total_batch_size, undefined)
})
