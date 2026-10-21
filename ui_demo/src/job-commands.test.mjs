import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createStrategy, createRuntimeConfig } from './data/defaults.js'
import { copyWorkflow } from './copy-workflow.js'
import { initializeJobCommands, refreshJobCommands, validateJobCommands } from './job-commands.js'

const defaults = { mixing: 'run mix', training: 'run train', evaluation: 'run eval' }

test('each job receives a full command, edits do not affect other jobs or defaults', () => {
  const strategies = [createStrategy(), createStrategy('manual'), createStrategy('random')]
  const runtime = createRuntimeConfig()
  initializeJobCommands(strategies, runtime, defaults)
  assert.ok(strategies.every(s => s.mixingCommand === defaults.mixing && s.trainingCommand === defaults.training))
  strategies[0].trainingCommand = 'custom training'
  runtime.commands.evaluation = 'custom eval'
  initializeJobCommands(strategies, runtime, defaults)
  assert.equal(strategies[0].trainingCommand, 'custom training')
  assert.equal(strategies[1].trainingCommand, 'run train')
  assert.equal(runtime.commands.evaluation, 'custom eval')
  assert.equal(defaults.evaluation, 'run eval')
  const added = createStrategy('manual')
  strategies.push(added)
  initializeJobCommands(strategies, runtime, defaults)
  assert.equal(added.trainingCommand, defaults.training)
})

test('cleared commands remain empty across navigation and fail validation instead of inheriting', () => {
  const strategy = createStrategy(), runtime = createRuntimeConfig()
  initializeJobCommands([strategy], runtime, defaults)
  strategy.mixingCommand = ''
  initializeJobCommands([strategy], runtime, defaults)
  assert.equal(strategy.mixingCommand, '')
  for (const value of ['', '  ', null, 'bad\0command', 'a'.repeat(32769)]) {
    strategy.mixingCommand = value
    assert.throws(() => validateJobCommands([{ owner: strategy, commandKey: 'mixingCommand', label: '策略 A 配比' }]), /策略 A 配比/)
  }
  strategy.mixingCommand = defaults.mixing
  assert.doesNotThrow(() => validateJobCommands([{ owner: strategy, commandKey: 'mixingCommand', label: '配比' }]))
})

test('initialized default commands follow the first and later configuration refreshes', () => {
  const strategies = [createStrategy(), createStrategy('manual'), createStrategy('random')]
  const runtime = createRuntimeConfig()
  initializeJobCommands(strategies, runtime, defaults)
  for (const address of ['obs://first-input', 'obs://changed-input']) {
    initializeJobCommands(strategies, runtime, defaults)
    const next = Object.fromEntries(Object.entries(defaults).map(([stage, command]) => [stage, `${command} --input ${address}`]))
    refreshJobCommands(strategies, runtime, next)
    assert.deepEqual(runtime.commands, next)
    for (const strategy of strategies) {
      assert.equal(strategy.mixingCommand, next.mixing)
      assert.equal(strategy.trainingCommand, next.training)
    }
  }
})

test('copying a workflow without shared commands replaces the previous workflow default baseline', () => {
  const runtime = createRuntimeConfig()
  const previousStrategies = [createStrategy()]
  initializeJobCommands(previousStrategies, runtime, defaults)
  refreshJobCommands(previousStrategies, runtime, { mixing: 'previous mix', training: 'previous train', evaluation: 'previous eval' })
  const copied = copyWorkflow({ resources: {}, training: {}, evaluation: { datasets: [] },
    strategies: [{ type: 'quadmix' }, { type: 'manual', training_command: 'custom training' }] })
  Object.assign(runtime, copied.runtime)
  assert.equal(runtime.commands, null)
  initializeJobCommands(copied.strategies, runtime, defaults)
  copied.strategies[1].mixingCommand = ''
  const next = { mixing: 'next mix', training: 'next train', evaluation: 'next eval' }
  refreshJobCommands(copied.strategies, runtime, next)
  assert.deepEqual(runtime.commands, next)
  assert.equal(copied.strategies[0].mixingCommand, next.mixing)
  assert.equal(copied.strategies[0].trainingCommand, next.training)
  assert.equal(copied.strategies[1].mixingCommand, '')
  assert.equal(copied.strategies[1].trainingCommand, 'custom training')
})

for (const evaluation of ['custom eval', '']) {
  test(`edits before the first refresh remain manual, including ${JSON.stringify(evaluation)} evaluation`, () => {
    const strategies = [createStrategy(), createStrategy('manual'), createStrategy('random')]
    const runtime = createRuntimeConfig()
    initializeJobCommands(strategies, runtime, defaults)
    strategies[0].mixingCommand = 'custom mixing'
    strategies[0].trainingCommand = ''
    strategies[1].mixingCommand = ''
    strategies[1].trainingCommand = 'custom training'
    Object.assign(runtime.commands, { mixing: 'custom shared mixing', training: '', evaluation })
    for (const address of ['obs://first-input', 'obs://changed-input']) {
      const next = Object.fromEntries(Object.entries(defaults).map(([stage, command]) => [stage, `${command} --input ${address}`]))
      refreshJobCommands(strategies, runtime, next)
      assert.equal(strategies[0].mixingCommand, 'custom mixing')
      assert.equal(strategies[0].trainingCommand, '')
      assert.equal(strategies[1].mixingCommand, '')
      assert.equal(strategies[1].trainingCommand, 'custom training')
      assert.equal(strategies[2].mixingCommand, next.mixing)
      assert.equal(strategies[2].trainingCommand, next.training)
      assert.deepEqual(runtime.commands, { mixing: 'custom shared mixing', training: '', evaluation })
    }
  })
}

test('copy expands legacy shared commands and preserves individual commands', () => {
  const copied = copyWorkflow({ resources: {}, training: {}, evaluation: { datasets: [] }, commands: defaults,
    strategies: [{ type: 'quadmix', mixing_command: 'custom mixing' }, { type: 'manual', mixing_command: '  ' }] })
  initializeJobCommands(copied.strategies, copied.runtime, { mixing: 'new mix', training: 'new train', evaluation: 'new eval' })
  assert.equal(copied.strategies[0].mixingCommand, 'custom mixing')
  assert.equal(copied.strategies[0].trainingCommand, defaults.training)
  assert.equal(copied.strategies[1].mixingCommand, defaults.mixing)
  assert.equal(copied.runtime.commands.evaluation, defaults.evaluation)
})

test('one editable command per planned job replaces the shared and override sections', () => {
  const review = readFileSync(new URL('./components/steps/ReviewSubmitStep.vue', import.meta.url), 'utf8')
  assert.match(review, /v-for="job in jobPlan"/)
  assert.match(review, /v-model="job.owner\[job.commandKey\]"/)
  assert.match(review, /validateJobCommands\(jobPlan.value\)/)
  assert.doesNotMatch(review, /单独设置 command|v-model="runtime.commands\.(mixing|training|evaluation)"/)
  const retry = readFileSync(new URL('./components/ParallelJobRetry.vue', import.meta.url), 'utf8')
  assert.match(retry, /validateJobCommands\(/)
})
