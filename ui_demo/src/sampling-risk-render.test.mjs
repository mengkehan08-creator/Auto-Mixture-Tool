import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { fileURLToPath } from 'node:url'

test('risk panel renders explicit warnings without changing the estimated training ratio', async () => {
  const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), server: { middlewareMode: true }, logLevel: 'error' })
  try {
    const { default: Panel } = await server.ssrLoadModule('/src/components/SamplingRisk.vue')
    const strategy = { type: 'quadmix', name: '测试策略', samplingBounds: { omega: [1, 1], epsilon: [0, 0], lambda: [0, 0], eta: [0, 0] } }
    const render = (budget, datasetTokens) => renderToString(createSSRApp(Panel, { strategy, budget, datasetTokens }))
    const warning = await render(4000000, 1000000)
    assert.match(warning, /role="alert"/)
    assert.match(warning, /4\.00 倍/)
    assert.match(warning, /告警：训练预算已超过预计采样量的 3 倍/)
    assert.match(warning, /仍可继续提交/)
    const normal = await render(2000000, 1000000)
    assert.match(normal, /role="status"/)
    assert.match(normal, /2\.00 倍/)
    assert.match(normal, /同一篇文本入选两次/)
    assert.doesNotMatch(normal, /告警：训练预算已超过/)
    const unknown = await render(4000000, undefined)
    assert.match(unknown, /请先校验输入数据/)
    assert.doesNotMatch(unknown, /NaN|Infinity|class="repeat-ratio"/)
  } finally {
    await server.close()
  }
})
