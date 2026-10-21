import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { createSSRApp, reactive } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { copyWorkflow } from './copy-workflow.js'
import { stemTasks } from './evaluation-selection.js'

let server, Evaluation, Review
before(async () => {
  server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), server: { middlewareMode: true, hmr: false, ws: false }, optimizeDeps: { noDiscovery: true }, logLevel: 'error' })
  Evaluation = (await server.ssrLoadModule('/src/components/steps/EvaluationConfigStep.vue')).default
  Review = (await server.ssrLoadModule('/src/components/steps/ReviewSubmitStep.vue')).default
})
after(async () => { await server?.close() })

function copiedWorkflow(datasets) {
  const copy = reactive(copyWorkflow({
    input_data_obs_uri: 'obs://bucket/input/', output_root_obs_uri: 'obs://bucket/output/',
    resources: {}, training: {}, strategies: [{ type: 'manual' }],
    commands: { mixing: 'run mix', training: 'run train', evaluation: 'run eval' },
    evaluation: { datasets },
  }))
  copy.runtime.datasetEstimate = { ready: true }
  return copy
}

const evaluationProps = copy => ({ config: copy.evaluation, training: copy.training, runtime: copy.runtime, strategies: copy.strategies })

// Run the real SFC setup without mounting network-polling child components.
async function setupState(Component, props, emit = () => {}) {
  let state
  await renderToString(createSSRApp({ setup() {
    state = Component.setup(props, { expose() {}, emit })
    return () => null
  } }))
  return state
}

async function submitAndRead(t, review) {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null
    calls.push({ url, body })
    let result
    if (url.endsWith('/workflows/validate')) result = { ready: true }
    else if (url.endsWith('/workflows') && options.method === 'POST') result = { id: 'created' }
    else if (url.endsWith('/workflows')) result = [{ id: 'created', jobs: [{ id: 'mock-job' }] }]
    else throw new Error(`Unexpected request: ${url}`)
    return new Response(JSON.stringify(result), { headers: { 'Content-Type': 'application/json' } })
  })
  const previousWindow = globalThis.window
  globalThis.window = { location: { pathname: '/ui', protocol: 'http:' }, crypto: { randomUUID: () => 'new-request' } }
  try {
    await review.submit()
    assert.equal(review.error.value, '')
    assert.equal(review.status.value, 'success')
    const submitted = calls.find(call => call.url.endsWith('/workflows') && call.body)?.body
    assert.ok(submitted)
    assert.deepEqual(calls.find(call => call.url.endsWith('/validate')).body.evaluation, submitted.evaluation)
    assert.equal(review.jobPlan.value.some(job => job.module === 'evaluation'), Boolean(submitted.evaluation.datasets.length || submitted.evaluation.obs_packages.length))
    return submitted
  } finally {
    if (previousWindow === undefined) delete globalThis.window
    else globalThis.window = previousWindow
    t.mock.restoreAll()
  }
}

test('copied all/core presets stay visible, can be removed, and are replaced before submission', async t => {
  for (const preset of ['all', 'core']) {
    const copy = copiedWorkflow([preset])
    const panel = await setupState(Evaluation, evaluationProps(copy))
    const review = await setupState(Review, copy)
    const html = await renderToString(createSSRApp(Evaluation, evaluationProps(copy)))
    assert.match(html, new RegExp(`aria-pressed="true"[^>]*>${preset}（原实验预设）`))
    assert.deepEqual((await submitAndRead(t, review)).evaluation.datasets, [preset])
    panel.toggleDataset(copy.evaluation, preset)
    assert.deepEqual(panel.selectedTasks.value, [])
    assert.deepEqual((await submitAndRead(t, review)).evaluation.datasets, [])
    copy.evaluation.dataset.names = [preset]
    panel.toggleDataset(copy.evaluation, 'arc_easy')
    assert.deepEqual((await submitAndRead(t, review)).evaluation.datasets, ['arc_easy'])
    copy.evaluation.dataset.names = [preset]
    copy.evaluation.dataset.names = panel.selectStemEvaluationTasks(copy.evaluation.dataset.names)
    assert.deepEqual(panel.selectedTasks.value, stemTasks)
    assert.deepEqual((await submitAndRead(t, review)).evaluation.datasets, stemTasks)
  }
})

test('copied mmlu_zeroshot remains visible and combines with STEM as an individual task', async t => {
  const copy = copiedWorkflow(['mmlu_zeroshot'])
  const panel = await setupState(Evaluation, evaluationProps(copy))
  const review = await setupState(Review, copy)
  const html = await renderToString(createSSRApp(Evaluation, evaluationProps(copy)))
  assert.match(html, /aria-pressed="true"[^>]*>mmlu_zeroshot/)
  copy.evaluation.dataset.names = panel.selectStemEvaluationTasks(copy.evaluation.dataset.names)
  assert.deepEqual((await submitAndRead(t, review)).evaluation.datasets, ['mmlu_zeroshot', ...stemTasks])
  panel.toggleDataset(copy.evaluation, 'mmlu_zeroshot')
  assert.deepEqual((await submitAndRead(t, review)).evaluation.datasets, stemTasks)
})

test('hidden OBS packages do not create a builtin evaluation and survive switching back', async t => {
  const copy = copiedWorkflow(['stem'])
  const panel = await setupState(Evaluation, evaluationProps(copy))
  const review = await setupState(Review, copy)
  const pack = { name: 'custom', obs_uri: 'obs://bucket/evaluation/' }
  copy.evaluation.obsPackages.push(pack)
  for (const task of stemTasks) panel.toggleDataset(copy.evaluation, task)
  assert.deepEqual(panel.selectedTasks.value, [])
  assert.equal(review.evaluationEnabled.value, true)
  assert.deepEqual((await submitAndRead(t, review)).evaluation.obs_packages, [pack])
  copy.evaluation.dataset.source = 'builtin'
  assert.equal(review.evaluationEnabled.value, false)
  assert.deepEqual(review.commandSettings.value.eval_packages, [])
  assert.deepEqual((await submitAndRead(t, review)).evaluation.obs_packages, [])
  assert.deepEqual(copy.evaluation.obsPackages, [pack])
  const html = await renderToString(createSSRApp(Review, copy))
  assert.doesNotMatch(html, /汇总评测/)
  assert.match(html, /未启用评测/)
  copy.evaluation.dataset.source = 'obs'
  assert.equal(review.evaluationEnabled.value, true)
  assert.deepEqual(review.commandSettings.value.eval_packages, [pack])
  assert.deepEqual((await submitAndRead(t, review)).evaluation.obs_packages, [pack])
  copy.evaluation.dataset.enabled = false
  assert.equal(review.evaluationEnabled.value, false)
  assert.deepEqual(review.commandSettings.value.eval_packages, [])
  assert.deepEqual((await submitAndRead(t, review)).evaluation.obs_packages, [])
  assert.deepEqual(copy.evaluation.obsPackages, [pack])
})

test('submission emits accepted before cloud jobs exist and emits created only after a job appears', async t => {
  const events = []
  const review = await setupState(Review, copiedWorkflow(['stem']), (...event) => events.push(event))
  let cloudJobReady = false
  t.mock.method(globalThis, 'fetch', async (url, options = {}) => {
    let result
    if (url.endsWith('/workflows/validate')) result = { ready: true }
    else if (url.endsWith('/workflows') && options.method === 'POST') result = { id: 'accepted-workflow' }
    else if (url.endsWith('/workflows')) {
      assert.deepEqual(events, [['accepted', 'accepted-workflow']])
      result = [{ id: 'accepted-workflow', status: 'SUBMITTING', jobs: [cloudJobReady ? { id: 'cloud-job' } : { status: 'WAITING' }] }]
    } else throw new Error(`Unexpected request: ${url}`)
    return new Response(JSON.stringify(result), { headers: { 'Content-Type': 'application/json' } })
  })
  const previousWindow = globalThis.window
  globalThis.window = { location: { pathname: '/ui', protocol: 'http:' }, crypto: { randomUUID: () => 'new-request' } }
  try {
    await review.submit()
    assert.equal(review.error.value, '')
    assert.equal(review.pendingId.value, 'accepted-workflow')
    assert.deepEqual(events, [['accepted', 'accepted-workflow']])
    cloudJobReady = true
    await review.loadWorkflows()
    assert.deepEqual(events, [['accepted', 'accepted-workflow'], ['created', 'accepted-workflow']])
    assert.equal(review.status.value, 'success')
  } finally {
    if (previousWindow === undefined) delete globalThis.window
    else globalThis.window = previousWindow
    t.mock.restoreAll()
  }
})
