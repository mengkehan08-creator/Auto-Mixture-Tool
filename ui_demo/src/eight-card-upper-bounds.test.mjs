import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { fileURLToPath } from 'node:url'
import { createStrategy, createTrainingConfig, trainingParameters, strategyOptions } from './data/defaults.js'
import { copyWorkflow } from './copy-workflow.js'
import { upperOnlyBounds } from './budget-estimates.js'
import { domainTokenShares } from './analysis-model-details.js'

test('new configuration exposes upper bounds without changing historical records', () => {
  const original = { omega: [.05, .3], eta: [.4, .8] }
  const normalized = upperOnlyBounds(original)
  assert.deepEqual(normalized.omega, [0, .3])
  assert.deepEqual(normalized.eta, [0, .8])
  assert.deepEqual(normalized.lambda, [0, 1000])
  assert.deepEqual(original.omega, [.05, .3])
  const source = { training: { devices_per_node: 4 }, evaluation: { datasets: [], devices_per_node: 1 },
    strategies: [{ type: 'quadmix', devices_per_node: 2, sampling_bounds: original }] }
  const copy = copyWorkflow(source)
  assert.equal(copy.training.devicesPerNode, 8)
  assert.equal(copy.evaluation.devicesPerNode, 8)
  assert.equal(copy.strategies[0].devicesPerNode, 8)
  assert.deepEqual(copy.strategies[0].samplingBounds.omega, [0, .3])
  assert.equal(source.training.devices_per_node, 4)
  assert.equal(trainingParameters({ ...createTrainingConfig(), devicesPerNode: 4 }).devices_per_node, 8)
  assert.equal(strategyOptions.find(s => s.value === 'manual').label, '自定义配比')
})

test('domain visualization uses valid reported fractions, never invented defaults', () => {
  assert.deepEqual(domainTokenShares({}), [])
  assert.deepEqual(domainTokenShares({ sampling: { domain_token_ratios_named: { math: .6, physics: 0, invalid: 2, negative: -1 } } }),
    [{ name: '数学', value: .6 }, { name: '物理', value: 0 }])
})

test('QuadMix form renders four upper inputs and a read-only eight-card field', async () => {
  const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)),
    server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true, include: [] }, logLevel: 'silent' })
  try {
    const { default: Form } = await server.ssrLoadModule('/src/components/strategy/QuadMixConfig.vue')
    const html = await renderToString(createSSRApp(Form, { modelValue: createStrategy() }))
    assert.equal((html.match(/aria-label="\w+ 搜索上限"/g) || []).length, 4)
    assert.doesNotMatch(html, /aria-label="\w+ 下限"/)
    assert.match(html, /value="8" readonly aria-label="每节点固定 8 张 NPU"/)
  } finally { await server.close() }
})
