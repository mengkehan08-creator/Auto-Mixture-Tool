import test, { after, afterEach, before, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { createSSRApp, reactive } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createEvaluationConfig, createRuntimeConfig, createStrategy, createTrainingConfig } from './data/defaults.js'

let server, Review, previousWindow
const message = '已为当前服务启用自动 IAM，提交时自动获取 Authorization。'
const commands = { mixing: 'run mix', training: 'run train', evaluation: 'run eval' }
const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

before(async () => {
  server = await createServer({ root: fileURLToPath(new URL('..', import.meta.url)), server: { middlewareMode: true, hmr: false, ws: false }, optimizeDeps: { noDiscovery: true }, logLevel: 'error' })
  Review = (await server.ssrLoadModule('/src/components/steps/ReviewSubmitStep.vue')).default
})
after(async () => { await server?.close() })
beforeEach(() => {
  previousWindow = globalThis.window
  globalThis.window = { location: { pathname: '/proxy/ui/', protocol: 'http:' } }
})
afterEach(() => {
  if (previousWindow === undefined) delete globalThis.window
  else globalThis.window = previousWindow
})

async function reviewState() {
  const props = reactive({
    strategies: [{ ...createStrategy('manual'), mixingCommand: commands.mixing, trainingCommand: commands.training }],
    training: createTrainingConfig(), evaluation: createEvaluationConfig(),
    runtime: { ...createRuntimeConfig(), commands: { ...commands }, datasetEstimate: { ready: true } },
  })
  props.runtime.modelarts.endpoint = 'https://modelarts.example.test'
  props.runtime.modelarts.authorization = 'manual-private-authorization'
  let state
  // Exercise the real SFC setup without mounting child components or job polling.
  await renderToString(createSSRApp({ setup() {
    state = Review.setup(props, { expose() {}, emit() {} })
    return () => null
  } }))
  return { props, state, html: () => renderToString(createSSRApp({ ...Review, setup: () => state }, props)) }
}

test('Authorization has a labelled password input and an adjacent IAM action', async () => {
  const review = await reviewState()
  const html = await review.html()
  assert.match(html, /<label for="modelarts-authorization"[^>]*>Authorization<\/label>/)
  assert.match(html, /id="modelarts-authorization"[^>]*type="password"/)
  assert.match(html, /<button[^>]*type="button"[^>]*>.*自动配置 IAM<\/button>/)
  for (const label of html.match(/<label\b[^]*?<\/label>/g)) assert.doesNotMatch(label, /<button/)
  assert.doesNotMatch(html, /AMT_IAM_PROVIDER|export |重启后端|已获取 Token/)
})

test('IAM setup sends only the endpoint, blocks duplicate clicks, and invalidates the old check on success', async t => {
  const review = await reviewState()
  let resolveRequest
  const request = t.mock.method(globalThis, 'fetch', (url, options) => {
    assert.equal(url, '/proxy/api/v1/iam/configure')
    assert.equal(options.method, 'POST')
    assert.equal(options.headers['Content-Type'], 'application/json')
    assert.deepEqual(JSON.parse(options.body), { endpoint: review.props.runtime.modelarts.endpoint })
    return new Promise(resolve => { resolveRequest = resolve })
  })
  review.state.validation.value = { ready: true, message: '旧配置检查' }
  review.state.status.value = 'success'
  review.state.error.value = '旧配置错误'

  const configuring = review.state.configureIam()
  assert.equal(review.state.iamConfiguring.value, true)
  await review.state.configureIam()
  assert.equal(request.mock.callCount(), 1)
  const pendingHtml = await review.html()
  assert.match(pendingHtml, /<button[^>]*disabled[^>]*>[^]*?正在配置 IAM…<\/button>/)
  assert.match(pendingHtml, /class="submission-actions"[^]*?<button[^>]*disabled/)

  resolveRequest(response({ auth_mode: 'iam', message }))
  await configuring
  assert.equal(review.state.authMode.value, 'iam')
  assert.equal(review.props.runtime.modelarts.authorization, '')
  assert.equal(review.state.validation.value, null)
  assert.equal(review.state.status.value, 'idle')
  assert.equal(review.state.error.value, '')
  assert.equal(review.state.iamConfiguring.value, false)
  const html = await review.html()
  assert.match(html, /role="status"[^>]*>已为当前服务启用自动 IAM，提交时自动获取 Authorization。/)
  assert.match(html, /id="modelarts-authorization"[^>]*value="自动获取（提交时执行）"[^>]*readonly/)
  assert.match(html, /重新配置 IAM/)
  assert.doesNotMatch(html, /manual-private-authorization|旧配置检查|旧配置错误|已获取 Token/)
})

test('a failed setup keeps manual Authorization and allows a successful retry', async t => {
  const review = await reviewState()
  let attempts = 0
  t.mock.method(globalThis, 'fetch', async url => {
    assert.equal(url, '/proxy/api/v1/iam/configure')
    return ++attempts === 1 ? response({ detail: 'IAM 配置不可用，请检查服务配置。' }, 400) : response({ auth_mode: 'iam', message })
  })
  await review.state.configureIam()
  assert.equal(review.state.authMode.value, 'manual')
  assert.equal(review.props.runtime.modelarts.authorization, 'manual-private-authorization')
  assert.equal(review.state.iamConfiguring.value, false)
  assert.equal(review.state.iamMessage.value, '')
  const html = await review.html()
  assert.match(html, /role="alert"[^>]*>IAM 配置不可用，请检查服务配置。/)
  assert.match(html, /id="modelarts-authorization"[^>]*type="password"/)
  assert.doesNotMatch(html, /role="alert"[^>]*>[^<]*manual-private-authorization/)
  await review.state.configureIam()
  assert.equal(attempts, 2)
  assert.equal(review.state.authMode.value, 'iam')
  assert.equal(review.state.iamError.value, '')
})

test('IAM mode is enabled only when confirmed by the service', async t => {
  const review = await reviewState()
  t.mock.method(globalThis, 'fetch', async () => response({ auth_mode: 'manual', message: '未配置' }))
  await review.state.configureIam()
  assert.equal(review.state.authMode.value, 'manual')
  assert.equal(review.props.runtime.modelarts.authorization, 'manual-private-authorization')
  assert.equal(review.state.iamMessage.value, '')
  assert.match(review.state.iamError.value, /尚未启用自动 IAM/)
})

test('missing ModelArts address is explained before making a setup request', async t => {
  const review = await reviewState()
  review.props.runtime.modelarts.endpoint = '   '
  const request = t.mock.method(globalThis, 'fetch', () => { throw new Error('No request expected') })
  await review.state.configureIam()
  assert.equal(request.mock.callCount(), 0)
  assert.equal(review.state.iamConfiguring.value, false)
  assert.equal(review.props.runtime.modelarts.authorization, 'manual-private-authorization')
  assert.match(review.state.iamError.value, /请先填写 ModelArts 作业 API 地址/)
})

test('IAM defaults show deferred authorization and still allow reconfiguration', async t => {
  const review = await reviewState()
  const paths = []
  t.mock.method(globalThis, 'fetch', async url => {
    paths.push(url)
    if (url.endsWith('/workflow-defaults')) return response({ auth_mode: 'iam', commands })
    if (url.endsWith('/workflow-commands')) return response({ commands })
    assert.ok(url.endsWith('/iam/configure'))
    return response({ auth_mode: 'iam', message })
  })
  await review.state.loadCommands()
  assert.equal(review.state.authMode.value, 'iam')
  assert.equal(review.props.runtime.modelarts.authorization, '')
  const html = await review.html()
  assert.match(html, /自动获取（提交时执行）/)
  assert.match(html, /重新配置 IAM/)
  assert.doesNotMatch(html, /已获取 Token/)
  await review.state.configureIam()
  assert.deepEqual(paths, ['/proxy/api/v1/workflow-defaults', '/proxy/api/v1/workflow-commands', '/proxy/api/v1/iam/configure'])
})

test('a check started before IAM setup cannot restore a stale success preview', async t => {
  const review = await reviewState()
  let resolveValidation
  t.mock.method(globalThis, 'fetch', async url => {
    if (url.endsWith('/workflows/validate')) return new Promise(resolve => { resolveValidation = resolve })
    assert.ok(url.endsWith('/iam/configure'))
    return response({ auth_mode: 'iam', message })
  })
  const checking = review.state.checkConfiguration()
  assert.equal(typeof resolveValidation, 'function')
  await review.state.configureIam()
  resolveValidation(response({ ready: true, message: '过期的手动配置检查' }))
  assert.equal(await checking, false)
  assert.equal(review.state.validation.value, null)
  assert.doesNotMatch(await review.html(), /过期的手动配置检查|配置检查通过/)
})

test('older workflow defaults cannot undo a successful IAM setup', async t => {
  const review = await reviewState()
  let resolveDefaults
  t.mock.method(globalThis, 'fetch', async url => {
    if (url.endsWith('/workflow-defaults')) return new Promise(resolve => { resolveDefaults = resolve })
    if (url.endsWith('/workflow-commands')) return response({ commands })
    assert.ok(url.endsWith('/iam/configure'))
    return response({ auth_mode: 'iam', message })
  })
  const loading = review.state.loadCommands()
  await review.state.configureIam()
  resolveDefaults(response({ auth_mode: 'manual', commands }))
  await loading
  assert.equal(review.state.authMode.value, 'iam')
  assert.equal(review.props.runtime.modelarts.authorization, '')
})
