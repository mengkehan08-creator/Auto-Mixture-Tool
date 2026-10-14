import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { fileURLToPath } from 'node:url'
import { readFileSync } from 'node:fs'
import { modelDetailRows, domainTokenSummary } from './analysis-model-details.js'
import { formatBillions } from './budget-estimates.js'

const model = {
  experiment_config: { type: 'quadmix', proxy_experiments: 50, proxy_steps: 15,
    sampling_bounds: { omega: [0, .2], epsilon: [0, .001], lambda: [0, 1000], eta: [1, 1] } },
  training: { token_budget: 401395843 },
  sampling: { tokens: 165000000, train_docs: 45678, token_method: 'nanochat tokenizer',
    domain_token_ratios_named: { 数学: .6, 物理: .4 } },
}

test('summary includes strategy, configured ranges, actual report counts and Chinese token shares', () => {
  const rows = modelDetailRows(model)
  assert.equal(rows.length, 11)
  assert.equal(rows[0].value, 'QuaDMix 算法')
  assert.equal(rows[1].value, '50')
  assert.equal(rows[2].value, '15')
  assert.equal(rows[3].value, '0 ～ 0.2')
  assert.equal(rows[6].value, '1（固定值）')
  assert.match(rows[7].value, /401,395,843/)
  assert.match(rows[8].value, /165,000,000/)
  assert.equal(rows[9].value, '45,678')
  assert.equal(domainTokenSummary(model), '数学 60.00% · 物理 40.00%')
  assert.equal(modelDetailRows({ experiment_config: { type: 'random' } }).length, 5)
  assert.equal(rows[10].value, '未记录')
  assert.equal(modelDetailRows({ experiment_config: { type: 'quadmix' } })[3].value, '未记录')
  assert.equal(domainTokenSummary({ sampling: { domain_ratios: { 0: .5 } } }), '领域 0（名称未记录） 50.00%')
})

test('B means billion tokens, missing and small values are not silently rounded to zero', () => {
  assert.equal(formatBillions(100000000000), '100.000 B Token')
  assert.equal(formatBillions(165000000), '0.165 B Token')
  assert.equal(formatBillions(100), '<0.001 B Token')
  assert.equal(formatBillions(0), '0.000 B Token')
  for (const value of [null, undefined, NaN, Infinity, -1]) assert.equal(formatBillions(value), '待统计')
})

test('actual training identity is displayed alongside the requested token budget', () => {
  const rows = modelDetailRows({ ...model, training: { ...model.training, actual_tokens: 401604608,
    total_batch_size: 524288, nodes: 4, world_size: 32, num_iterations: 766, grad_accum_steps: 8 } })
  assert.match(rows.find(r => r.label === '实际训练 Token 数').value, /401,604,608/)
  assert.equal(rows.find(r => r.label === '训练节点 / 全局 NPU 数').value, '4 / 32')
  assert.equal(rows.find(r => r.label === '梯度累积次数').value, '8')
})

test('winner summary and successful dataset check render readable named fields', async () => {
  const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, logLevel: 'error' })
  try {
    const { default: Summary } = await server.ssrLoadModule('/src/components/ModelExperimentSummary.vue')
    const html = await renderToString(createSSRApp(Summary, { model }))
    for (const text of ['配比策略', '代理实验数', '代理实验步数', 'ω', 'ε', 'λ', 'η', '训练 Token 预算', '训练文档数', '数学 60.00%', '物理 40.00%', '不是搜索后最终选定的参数']) assert.ok(html.includes(text), text)
    const form = readFileSync(new URL('./components/steps/MixingStrategyStep.vue', import.meta.url), 'utf8')
    assert.match(form, /formatBillions\(runtime.datasetEstimate.estimated_tokens\)/)
    assert.match(form, /1 B = 10 亿 Token/)
    assert.match(form, /GiB/)
  } finally { await server.close() }
})
