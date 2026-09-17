import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { fileURLToPath } from 'node:url'
import { createStrategy } from './data/defaults.js'

test('batch dialog renders readable preview, inherited settings and explicit confirmation', async () => {
  const server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), server: { middlewareMode: true }, logLevel: 'error' })
  try {
    const { default: Dialog } = await server.ssrLoadModule('/src/components/strategy/QuadMixBatchDialog.vue')
    const context = {}
    await renderToString(createSSRApp(Dialog, { source: createStrategy() }), context)
    const html = context.teleports.body
    assert.match(html, /QuaDMix 批量配置/)
    assert.match(html, /15 个组合/)
    assert.match(html, /确认加入 15 项策略/)
    assert.match(html, /4,500/)
    assert.match(html, /ex-500-5000-0p3/)
    assert.match(html, /此处不会启动云端作业/)
    assert.equal((html.match(/aria-label="选择组合 /g) || []).length, 15)
    assert.match(html, /搜索下限/)
    assert.match(html, /固定值/)
    assert.match(html, /本批次节点配置/)
    assert.match(html, /配比 2 节点 · 训练 2 节点/)
    assert.equal((html.match(/type="number" min="1" max="16"/g) || []).length, 1)
    assert.match(html, /使用统一默认值（2 节点）/)
  } finally { await server.close() }
})
