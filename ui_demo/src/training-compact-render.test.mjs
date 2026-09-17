import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { fileURLToPath } from 'node:url'
import { createStrategy, createTrainingConfig, createRuntimeConfig } from './data/defaults.js'

test('training page renders one shared schedule and collapsed risk details', async () => {
  const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), server: { middlewareMode: true }, logLevel: 'error' })
  try {
    const { default: Panel } = await server.ssrLoadModule('/src/components/steps/TrainingConfigStep.vue')
    const strategies = Array.from({ length: 15 }, () => ({ ...createStrategy(),
      samplingBounds: { omega: [1, 1], epsilon: [0, 0], lambda: [0, 0], eta: [0, 0] } }))
    strategies[0].trainingNodesOverride = 4
    const config = { ...createTrainingConfig(), tokenBudget: 4000000 }
    const runtime = { ...createRuntimeConfig(), datasetEstimate: { estimated_tokens: 1000000 } }
    const html = await renderToString(createSSRApp(Panel, { strategies, config, runtime }))
    assert.equal((html.match(/默认训练节点数/g) || []).length, 1)
    assert.equal((html.match(/训练任务优先级/g) || []).length, 1)
    assert.match(html, /15 项告警/)
    assert.match(html, /4\.00 倍/)
    assert.match(html, /1 项策略使用单独节点数/)
    assert.match(html, /查看详细说明与各策略预判/)
    assert.doesNotMatch(html, /class="sampling-risk|举例：某篇文本|训练作业名称（可自定义）|保存模型名称/)
    const unknown = await renderToString(createSSRApp(Panel, { strategies, config, runtime: createRuntimeConfig() }))
    assert.match(unknown, /15 项策略暂无法预估/)
    assert.doesNotMatch(unknown, /NaN|Infinity/)
  } finally { await server.close() }
})
