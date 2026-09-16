import test from 'node:test'
import assert from 'node:assert/strict'
import { defaultSamplingBounds, proxyTrainingTokens, sampleScenario, samplingRisk, validBounds } from './budget-estimates.js'
import { createStrategy } from './data/defaults.js'
import { parameterName } from './strategy-names.js'
import { readFileSync } from 'node:fs'

test('new strategies default to 50 experiments and explicit counts remain editable', () => {
  const strategy = createStrategy()
  assert.equal(strategy.proxyExperiments, 50)
  assert.equal(parameterName({ type: 'quadmix' }), 'ex-50-15')
  strategy.proxyExperiments = 16
  assert.equal(parameterName(strategy), 'ex-16-15')
})

test('proxy consumption is per experiment and changes with training steps only', () => {
  assert.equal(proxyTrainingTokens(15), 245760)
  assert.equal(proxyTrainingTokens(5000), 81920000)
  assert.equal(proxyTrainingTokens(0), null)
})
test('unknown data never becomes a sample prediction', () => {
  assert.equal(sampleScenario(undefined, defaultSamplingBounds()), null)
  assert.equal(samplingRisk(401000000, null).ratio, null)
})
test('effective ranges validate and defaults are independent per strategy', () => {
  const a = createStrategy(), b = createStrategy()
  a.samplingBounds.omega[1] = 0.2
  assert.equal(b.samplingBounds.omega[1], 0.1)
  assert.ok(validBounds(a.samplingBounds))
  for (const pair of [[.2, .1], [0, 1.1], [NaN, 1], ['', .1]]) assert.equal(validBounds({ ...a.samplingBounds, omega: pair }), false)
})
test('scenario follows the sampling function, not proxy count or steps', () => {
  const fixed = { omega: [.1, .1], epsilon: [.001, .001], lambda: [0, 0], eta: [1, 1] }
  const result = sampleScenario(1000000, fixed)
  assert.ok(Math.abs(result.midpoint - 101000) < 1e-6)
  assert.equal(result.low, result.high)
  for (const key of ['omega', 'epsilon', 'lambda', 'eta']) {
    const small = { omega: [.05, .05], epsilon: [.0005, .0005], lambda: [100, 100], eta: [.3, .3] }
    const larger = structuredClone(small); larger[key] = larger[key].map(n => n * 2)
    assert.ok(sampleScenario(1000000, larger).midpoint > sampleScenario(1000000, small).midpoint)
  }
})
test('risk uses data and configured ranges, warning strictly above three', () => {
  const bounds = { omega: [.1, .1], epsilon: [0, 0], lambda: [0, 0], eta: [0, 0] }
  const scenario = sampleScenario(1650000000, bounds)
  assert.equal(scenario.midpoint, 165000000)
  assert.equal(samplingRisk(401000000, scenario).warning, false)
  assert.equal(samplingRisk(495000000, scenario).warning, false)
  assert.equal(samplingRisk(495000001, scenario).warning, true)
  const reduced = sampleScenario(1650000000, { ...bounds, omega: [.05, .05] })
  assert.equal(samplingRisk(401000000, reduced).warning, true)
  assert.equal(samplingRisk(401000000, reduced).ratio, samplingRisk(401000000, scenario).ratio * 2)
  assert.equal(samplingRisk(401000000, sampleScenario(1650000000, { ...bounds, omega: [0, 0] })).warning, true)
})

test('risk UI has no manual sampled-token input or override', () => {
  const source = readFileSync(new URL('./components/SamplingRisk.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /sampleTokens|<input|已有实际采样统计/)
  assert.match(source, /sampleScenario\(props.datasetTokens, props.strategy.samplingBounds/)
  assert.match(source, /samplingRisk\(props.budget, scenario.value\)/)
})
