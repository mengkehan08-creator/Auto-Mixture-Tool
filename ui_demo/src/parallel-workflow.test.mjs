import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createStrategy, createEvaluationConfig, createTrainingConfig } from './data/defaults.js'
import { copyWorkflow } from './copy-workflow.js'
import { stageIndex, statusView } from './workflow-state.js'

test('strategy nodes and training overrides are independent', () => {
  const a = createStrategy('quadmix'), b = createStrategy('manual')
  a.mixingNodes = 4; a.trainingOverrides.token_budget = 15
  assert.equal(b.mixingNodes, 1)
  assert.deepEqual(b.trainingOverrides, { token_budget: 401395843, device_batch_size: 1, devices_per_node: 8, eval_every: -1, core_metric_every: -1, batch_size_mode: 'auto' })
  assert.equal(createTrainingConfig().nodes, 2)
  assert.deepEqual(createEvaluationConfig().modelIds, [])
})

test('copy preserves per-job settings but clears external names', () => {
  const c = copyWorkflow({ input_data_obs_uri: 'obs://bucket/data', output_root_obs_uri: 'obs://bucket/out',
    mixing_nodes: 2, training_nodes: 2, resources: {}, training: {},
    evaluation: { datasets: ['stem'], model_ids: ['old:random'] },
    strategies: [{ id: 'quadmix', type: 'quadmix', mixing_nodes: 5, training_nodes: 7,
      mixing_job_name: 'old-mix', training_job_name: 'old-train', model_name: 'named-model', training: { token_budget: 15 } }] })
  assert.equal(c.strategies[0].mixingNodes, 5)
  assert.equal(c.strategies[0].trainingNodes, 7)
  assert.equal(c.strategies[0].mixingJobName, '')
  assert.equal(c.strategies[0].trainingJobName, '')
  assert.equal(c.strategies[0].trainingOverrides.token_budget, 15)
  assert.deepEqual(c.evaluation.modelIds, ['old:random'])
})

test('parallel status uses module rather than fixed array position', () => {
  const w = { pipeline_version: 4, status: 'RUNNING', jobs: [
    { module: 'mixing', id: 'm1' }, { module: 'training', id: 't1' },
    { module: 'mixing', id: 'm2' }, { module: 'training' }, { module: 'evaluation' }] }
  assert.equal(stageIndex(w), 3)
  w.jobs[4].id = 'evaluation'
  assert.equal(stageIndex(w), 5)
  assert.equal(statusView('BLOCKED').tone, 'warning')
})

test('creation and retries use real graph API without returning to wizard', () => {
  const review = readFileSync(new URL('./components/steps/ReviewSubmitStep.vue', import.meta.url), 'utf8')
  assert.match(review, /execution_mode: 'parallel'/)
  assert.match(review, /training_nodes: item.trainingNodes/)
  assert.match(review, /model_ids:/)
  const retry = readFileSync(new URL('./components/ParallelJobRetry.vue', import.meta.url), 'utf8')
  assert.match(retry, /jobs\/\$\{props.job.key\}\/retry/)
  assert.doesNotMatch(retry, /navigate\('create'/)
})
