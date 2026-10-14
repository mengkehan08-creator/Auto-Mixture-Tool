import test from 'node:test'
import assert from 'node:assert/strict'
import { batchExample, planQuadMixBatch, materializeQuadMixBatch } from './quadmix-batch.js'
import { createStrategy } from './data/defaults.js'
import { parameterName } from './strategy-names.js'
import { initializeJobCommands } from './job-commands.js'

test('batch nodes default to source and override only newly generated strategies', () => {
  const source = createStrategy()
  source.mixingNodes = 3
  source.trainingNodes = 4
  const inherited = materializeQuadMixBatch(source, planQuadMixBatch(source, batchExample()))
  assert.ok(inherited.every(s => s.mixingNodes === 3 && s.trainingNodes === 4))
  const changed = materializeQuadMixBatch(source, planQuadMixBatch(source, { ...batchExample(), mixingNodes: 1, trainingNodes: 16, overrideTrainingNodes: true }))
  assert.equal(changed.length, 15)
  assert.ok(changed.every(s => s.mixingNodes === 1 && s.trainingNodes === 16))
  assert.equal(source.mixingNodes, 3)
  assert.equal(source.trainingNodes, 4)
  assert.ok(inherited.every(s => s.mixingNodes === 3 && s.trainingNodes === 4))
})

test('batch node counts must be integers from one to sixteen', () => {
  for (const key of ['mixingNodes', 'trainingNodes']) for (const value of [0, -1, 17, 2.5, '', NaN, Infinity, true]) {
    assert.throws(() => planQuadMixBatch(createStrategy(), { ...batchExample(), overrideTrainingNodes: true, trainingNodes: 2, [key]: value }), /1～16/)
  }
})

test('example generates 15 distinct combinations with omega upper limits, not fixed omega', () => {
  const source = createStrategy()
  const before = JSON.stringify(source)
  const rows = planQuadMixBatch(source, batchExample())
  assert.equal(rows.length, 15)
  assert.equal(new Set(rows.map(r => r.key)).size, 15)
  assert.equal(rows.reduce((n, r) => n + r.proxyExperiments, 0), 4500)
  for (const upper of [.1, .15, .2, .25, .3]) {
    assert.deepEqual(rows.filter(r => r.samplingBounds.omega[1] === upper).map(r => r.proxyExperiments), [100, 300, 500])
  }
  assert.ok(rows.every(r => r.proxySteps === 5000 && r.samplingBounds.omega[0] === 0))
  assert.equal(JSON.stringify(source), before)
})

test('only upper sweeps are allowed; all copied lower bounds reset to zero', () => {
  const source = createStrategy()
  source.samplingBounds.lambda = [500, 1000]
  for (const parameter of ['omega', 'epsilon', 'lambda', 'eta']) {
    const plan = planQuadMixBatch(source, { experiments: '50', steps: '15,30', parameter, mode: 'upper', values: '0, 0.001' })
    assert.equal(plan.length, 4)
    assert.deepEqual(plan[2].samplingBounds[parameter], [0, .001])
    assert.ok(plan.every(row => Object.values(row.samplingBounds).every(pair => pair[0] === 0)))
  }
  for (const mode of ['lower', 'fixed']) assert.throws(() => planQuadMixBatch(source, { ...batchExample(), mode }), /仅支持设置搜索上限/)
})

test('parsing deduplicates values and accepts Chinese commas, spaces and newlines', () => {
  const rows = planQuadMixBatch(createStrategy(), { ...batchExample(), experiments: '100，100 300\n500', steps: '15;15', values: '.2, 0.20；0.3' })
  assert.equal(rows.length, 6)
})

test('invalid, reversed and oversized combinations are rejected before materialization', () => {
  const source = createStrategy()
  for (const bad of [{ experiments: '' }, { experiments: '1.5' }, { steps: '-1' }, { steps: 'Infinity' },
    { values: 'abc' }, { values: '-.1' }, { values: '1.1' }, { mode: 'lower', values: '.2' },
    { parameter: 'unknown' }, { mode: 'unknown' }]) {
    assert.throws(() => planQuadMixBatch(source, { ...batchExample(), ...bad }))
  }
  assert.throws(() => planQuadMixBatch(source, { ...batchExample(), experiments: Array.from({ length: 201 }, (_, i) => i + 1).join(',') }), /1000/)
})

test('chosen rows become independent strategies, preserve settings and retain command initialization', () => {
  const source = createStrategy()
  Object.assign(source, { seed: 123, searchCount: 6000, mixingNodes: 3, trainingNodes: 4,
    mixingPriority: 3, name: 'source', mixingJobName: 'custom-mixing', trainingJobName: 'custom-training', modelName: 'custom-model' })
  source.trainingOverrides.token_budget = 888888
  source.trainingCommand = 'python custom-train.py'
  const before = JSON.stringify(source)
  const rows = planQuadMixBatch(source, batchExample())
  const strategies = materializeQuadMixBatch(source, [rows[0], rows[6]])
  assert.equal(new Set([source.id, ...strategies.map(s => s.id)]).size, 3)
  assert.equal(parameterName(strategies[1]), 'ex-100-5000-0p2')
  for (const s of strategies) {
    for (const key of ['seed', 'searchCount', 'mixingNodes', 'trainingNodes', 'mixingPriority', 'trainingCommand']) assert.equal(s[key], source[key])
    assert.ok(['name', 'mixingJobName', 'trainingJobName', 'modelName'].every(key => s[key] === ''))
    assert.deepEqual(s.trainingOverrides, source.trainingOverrides)
  }
  initializeJobCommands(strategies, {}, { mixing: 'python mix.py', training: 'python train.py' })
  assert.equal(strategies[0].mixingCommand, 'python mix.py')
  assert.equal(strategies[0].trainingCommand, 'python custom-train.py')
  strategies[0].samplingBounds.lambda[0] = 10
  strategies[0].trainingOverrides.token_budget = 42
  assert.equal(strategies[1].samplingBounds.lambda[0], 0)
  assert.equal(strategies[1].trainingOverrides.token_budget, 888888)
  assert.equal(JSON.stringify(source), before)
})
