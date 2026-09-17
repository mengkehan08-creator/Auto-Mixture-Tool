import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { retryDraft, retryBody } from './stage-retry.js'

test('inline retry preserves source strategy IDs, clears credentials and uses current commands', () => {
  const config = { request_id: 'old', strategies: [{ id: 'manual_a', type: 'manual' }],
    commands: { training: 'old command' }, modelarts: { authorization: 'secret', pool_id: 'pool' },
    training: { token_budget: 123 }, evaluation: { datasets: ['stem'] },
    resources: { code_obs_uri: 'obs://bucket/old/' },
    offline_resources: [{ role: 'code_obs_uri', name: 'custom-code', uri: 'obs://bucket/old/' }],
  }
  const before = structuredClone(config)
  const draft = retryDraft(config, { commands: { training: 'fixed command' } }, { id: 'abc123' }, 'training')
  assert.deepEqual(draft.reuse, { workflow_id: 'abc123', stage: 'training' })
  assert.equal(draft.request_id, undefined)
  assert.equal(draft.modelarts.authorization, '')
  assert.equal(draft.commands.training, 'fixed command')
  assert.equal(draft.strategies[0].id, 'manual_a')
  assert.equal(draft.evaluation.datasets.length, 6)
  draft.resources.code_obs_uri = 'obs://bucket/fixed/'
  draft.training.token_budget = ''
  const body = retryBody(draft)
  assert.equal(body.offline_resources[0].uri, 'obs://bucket/fixed/')
  assert.equal(body.offline_resources[0].name, 'custom-code')
  assert.equal(body.training.token_budget, undefined)
  assert.deepEqual(config, before)
})

test('retry is rendered in workflow details, not routed to the experiment wizard', () => {
  const jobs = readFileSync(new URL('./components/WorkflowJobs.vue', import.meta.url), 'utf8')
  const app = readFileSync(new URL('./App.vue', import.meta.url), 'utf8')
  const panel = readFileSync(new URL('./components/StageRetryPanel.vue', import.meta.url), 'utf8')
  assert.ok(jobs.includes('<StageRetryPanel'))
  assert.ok(!app.includes('restartJob'))
  assert.ok(!jobs.includes("emit('restart'"))
  assert.ok(panel.includes("apiRequest('workflows'"))
  assert.ok(panel.includes('提交阶段重试'))
})

test('both retry forms open in a modal with loading errors and confirmation', () => {
  const jobs = readFileSync(new URL('./components/WorkflowJobs.vue', import.meta.url), 'utf8')
  const dialog = readFileSync(new URL('./components/RetryDialog.vue', import.meta.url), 'utf8')
  assert.match(jobs, /<RetryDialog v-if="retryStage \|\| retryJob"/)
  assert.match(dialog, /dialog.value.showModal\(\)/)
  assert.match(dialog, /@cancel.prevent/)
  for (const name of ['StageRetryPanel', 'ParallelJobRetry']) {
    const panel = readFileSync(new URL(`./components/${name}.vue`, import.meta.url), 'utf8')
    assert.match(panel, /role="alert"/)
    assert.match(panel, /重新加载配置/)
    assert.match(panel, /<ConfirmationDialog/)
  }
  const parallel = readFileSync(new URL('./components/ParallelJobRetry.vue', import.meta.url), 'utf8')
  assert.match(parallel, /resources: \{ ...resources \}/)
  assert.match(parallel, /v-model="training.output_obs_uri"/)
  assert.match(parallel, /v-model="item.obs_uri"/)
  assert.match(parallel, /v-model="evaluation.output_obs_uri"/)
  const legacy = readFileSync(new URL('./components/StageRetryPanel.vue', import.meta.url), 'utf8')
  assert.match(legacy, /<form v-if="draft"/)
})
