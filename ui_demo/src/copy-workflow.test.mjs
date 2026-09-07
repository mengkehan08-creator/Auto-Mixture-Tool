import test from 'node:test'
import assert from 'node:assert/strict'
import { copyWorkflow } from './copy-workflow.js'
import { createRuntimeConfig, createTrainingConfig } from './data/defaults.js'
test('OBS defaults match deployed script resources including proxy validation', () => {
  const runtime = createRuntimeConfig()
  assert.equal(runtime.codeObsUri, 'obs://bucket-pangu-green-guangzhou/s00944147/l00916525/Auto-Mixture-Tool/')
  assert.ok(runtime.inputDataObsUri.endsWith('chengchao/prepared_parquet_57ffce0ca0a2/'))
  assert.equal(runtime.proxyValidationObsUri, 'obs://bucket-pangu-green-guangzhou/s00944147/l00916525/AMT_old/data/')
  assert.ok(createTrainingConfig().modelObsUri.includes('backup_0810/work/'))
})
test('copy restores settings but never credentials or job identifiers', () => {
  const source = { request_id: 'old-request', experiment_name: 'experiment', mixing_nodes: 3, training_nodes: 4,
    input_data_obs_uri: 'obs://bucket/input', output_root_obs_uri: 'obs://bucket/output',
    modelarts: { authorization: 'secret', region: 'cn-south-1' },
    training: { model: 'NanoChat-Base', base_model_tag: 'd24', target_param_data_ratio: 0.5, devices_per_node: 8 },
    evaluation: { datasets: ['mmlu_stem'] }, resources: { nanochat_repo_obs_uri: 'obs://bucket/code' },
    strategies: [{ id: 'old-plan', type: 'manual', ratios: { 数学: 1 }, script_obs_uri: 'obs://bucket/custom.py', script_config: { limit: 2 } }],
  }
  const copy = copyWorkflow(source)
  assert.equal(copy.runtime.modelarts.authorization, '')
  assert.equal(copy.runtime.mixingNodes, 3)
  assert.equal(copy.training.nodes, 4)
  assert.equal(copy.runtime.outputRootObsUri, source.output_root_obs_uri)
  assert.equal(copy.strategies[0].scriptObsUri, 'obs://bucket/custom.py')
  assert.notEqual(copy.strategies[0].id, 'old-plan')
  copy.strategies[0].ratios.数学 = 0.5
  assert.equal(source.strategies[0].ratios.数学, 1)
  assert.ok(!JSON.stringify(copy).includes('old-request'))
})
