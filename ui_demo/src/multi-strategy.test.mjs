import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createStrategy, createRuntimeConfig, createEvaluationConfig } from './data/defaults.js'
import { copyWorkflow } from './copy-workflow.js'
import { strategyId, strategyNameHint, strategyLabel, trainingNameHint } from './strategy-names.js'

test('repeated types retain unique ids, independent parameters and new defaults', () => {
  const strategies = ['quadmix', 'quadmix', 'quadmix', 'manual', 'manual', 'random', 'random'].map(createStrategy)
  assert.equal(new Set(strategies.map(strategyId)).size, 7)
  assert.ok(strategies.every(s => s.mixingPriority === 2 && s.trainingPriority === 2))
  assert.equal(createEvaluationConfig().priority, 2)
  assert.equal(strategies[0].searchCount, 5000)
  strategies[0].proxySteps = 100
  strategies[3].ratios['数学'] = .8
  strategies[5].seed = 99
  assert.equal(strategies[1].proxySteps, 15)
  assert.equal(strategies[4].ratios['数学'], .6)
  assert.equal(strategies[6].seed, 42)
  assert.equal(strategyNameHint(strategies[0]), 'ex-16-100-{提交时间}')
  assert.match(trainingNameHint(strategies[0]), /^train-ex-16-100-t401395843-/)
  strategies[0].name = '自定义'
  assert.equal(strategyLabel(strategies[0]), '自定义')
})

test('submission uses unique ids for every type and add actions are in sticky header', () => {
  const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  assert.match(source('./components/steps/ReviewSubmitStep.vue'), /id: strategyId\(item\)/)
  const app = source('./App.vue')
  const header = app.slice(app.indexOf('<div class="workspace-header">'), app.indexOf('<WorkflowJobs'))
  assert.match(header, /<StrategyActions/)
  assert.match(source('./components/StrategyActions.vue'), /strategies.push\(createStrategy\(type\)\)/)
  assert.doesNotMatch(source('./components/StrategyActions.vue'), /strategies.length >=/)
  assert.doesNotMatch(source('./components/steps/MixingStrategyStep.vue'), /增加配比策略/)
  for (const component of ['ManualMixConfig', 'RandomMixConfig']) {
    const ui = source(`./components/strategy/${component}.vue`)
    assert.match(ui, /v-model.number="modelValue.seed" type="number"/)
    assert.doesNotMatch(ui, /不支持按.*单独覆盖/)
  }
})

test('hundreds of strategies remain distinct and concurrency survives copy', () => {
  const strategies = Array.from({ length: 200 }, (_, i) => createStrategy(['quadmix', 'manual', 'random'][i % 3]))
  assert.equal(new Set(strategies.map(strategyId)).size, 200)
  assert.equal(createRuntimeConfig().maxActiveJobs, 8)
  assert.equal(copyWorkflow({ resources: {}, strategies: [], training: {}, evaluation: { datasets: [] }, max_active_jobs: 3 }).runtime.maxActiveJobs, 3)
  const review = readFileSync(new URL('./components/steps/ReviewSubmitStep.vue', import.meta.url), 'utf8')
  assert.match(review, /max_active_jobs: props.runtime.maxActiveJobs/)
  assert.match(review, /v-model.number="runtime.maxActiveJobs"/)
})

test('framework source and OBS directory are independent and preserved on copy', () => {
  const a = createStrategy('quadmix'), b = createStrategy('random')
  a.trainingFrameworkSource = 'obs'
  a.trainingFrameworkObsUri = 'obs://bucket/custom-nanochat/'
  assert.equal(b.trainingFrameworkSource, 'builtin')
  assert.equal(b.trainingFrameworkObsUri, '')
  const copied = copyWorkflow({ resources: {}, training: {}, evaluation: { datasets: [], priority: 3 }, strategies: [
    { type: 'quadmix', training_framework_source: 'obs', training_framework_obs_uri: a.trainingFrameworkObsUri, training_priority: 1 },
  ] })
  assert.equal(copied.strategies[0].trainingFrameworkObsUri, a.trainingFrameworkObsUri)
  assert.equal(copied.strategies[0].trainingFrameworkSource, 'obs')
  assert.equal(copied.strategies[0].trainingPriority, 1)
  assert.equal(copied.evaluation.priority, 3)
  const training = readFileSync(new URL('./components/steps/TrainingConfigStep.vue', import.meta.url), 'utf8')
  assert.match(training, /v-model="strategy.trainingFrameworkObsUri"/)
  assert.match(training, /strategy.trainingFrameworkSource = 'obs'/)
  const review = readFileSync(new URL('./components/steps/ReviewSubmitStep.vue', import.meta.url), 'utf8')
  assert.match(review, /training_framework_obs_uri: item.trainingFrameworkObsUri/)
  assert.match(readFileSync(new URL('./components/StrategyActions.vue', import.meta.url), 'utf8'), /min-width: 172px/)
})
