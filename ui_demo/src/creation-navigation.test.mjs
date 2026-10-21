import test, { after, before } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'

let server, App
before(async () => {
  server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), server: { middlewareMode: true, hmr: false, ws: false }, optimizeDeps: { noDiscovery: true }, logLevel: 'error' })
  ;({ default: App } = await server.ssrLoadModule('/src/App.vue'))
})
after(async () => { await server?.close() })

async function createState(t) {
  const requests = t.mock.method(globalThis, 'fetch', () => { throw new Error('Creation navigation must not request cloud APIs') })
  t.after(() => assert.equal(requests.mock.callCount(), 0))
  let state
  // Run the real setup in an SSR scope without mounting children that poll cloud jobs.
  await renderToString(createSSRApp({ setup() {
    state = App.setup({}, { expose() {} })
    return () => null
  } }))
  return state
}

function configuration(state) {
  return JSON.parse(JSON.stringify({ step: state.currentStep.value, version: state.formVersion.value,
    runtime: state.runtime, training: state.training, evaluation: state.evaluation,
    strategies: state.strategies.map(({ id, ...strategy }) => strategy) }))
}

function editConfiguration(state) {
  state.runtime.experimentName = 'unfinished experiment'
  state.runtime.inputDataObsUri = 'obs://example/edited-input/'
  state.training.nodes = 3
  state.training.tokenBudget = 123456789
  state.evaluation.maxPerTask = 7
  state.evaluation.api.key = 'unsaved-credential'
  state.strategies[0].proxySteps = 31
  state.strategies[1].ratios.数学 = 0.7
  state.navigate('create', 3)
}

test('sidebar jobs → create preserves edited parameters and the current step without asking to clear them', async t => {
  const state = await createState(t)
  editConfiguration(state)
  const edited = configuration(state)
  const strategyIds = state.strategies.map(strategy => strategy.id)

  state.sidebarNavigate('jobs')
  assert.equal(state.page.value, 'jobs')
  assert.equal(state.resetVisible.value, false)
  state.sidebarNavigate('create')

  assert.equal(state.page.value, 'create')
  assert.equal(state.resetVisible.value, false)
  assert.deepEqual(configuration(state), edited)
  assert.deepEqual(state.strategies.map(strategy => strategy.id), strategyIds)
})

test('clicking create again keeps the current form and does not open confirmation or add history', async t => {
  const state = await createState(t)
  editConfiguration(state)
  const edited = configuration(state)
  const historyLength = state.navigationHistory.value.length

  state.sidebarNavigate('create')
  state.sidebarNavigate('create')

  assert.equal(state.resetVisible.value, false)
  assert.deepEqual(configuration(state), edited)
  assert.equal(state.navigationHistory.value.length, historyLength)
})

test('explicit new-experiment confirmation clears the edited form only when accepted', async t => {
  const state = await createState(t)
  const defaults = configuration(state)
  editConfiguration(state)
  state.runtime.extraDraftField = 'must be removed'
  const edited = configuration(state)

  state.resetVisible.value = true
  assert.deepEqual(configuration(state), edited)
  state.resetExperiment()

  assert.equal(state.resetVisible.value, false)
  assert.equal(state.page.value, 'create')
  assert.deepEqual(configuration(state), { ...defaults, version: defaults.version + 1 })
  assert.deepEqual(state.navigationHistory.value, [])
  assert.equal(state.selectedId.value, '')
})

test('cancelling explicit new-experiment confirmation preserves all edits and the current step', async t => {
  const state = await createState(t)
  editConfiguration(state)
  const edited = configuration(state)

  state.resetVisible.value = true
  state.resetVisible.value = false

  assert.equal(state.page.value, 'create')
  assert.deepEqual(configuration(state), edited)
})
