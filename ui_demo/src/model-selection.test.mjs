import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { searchModels, selectModel } from './model-selection.js'
import { workflowPage } from './workflow-state.js'
import { createStrategy } from './data/defaults.js'
import { copyWorkflow } from './copy-workflow.js'

const models = Array.from({ length: 12 }, (_, index) => ({
  id: `model-${index}`, name: index % 2 ? `随机-${index}` : `QuadMix-${index}`,
  workflow_name: `实验-${index}`, workflow_id: `workflow-${index}`,
}))

test('multiple model queries match any keyword, case-insensitively, before pagination', () => {
  assert.equal(searchModels(models, ' QUADMIX，随机 ').length, 12)
  assert.deepEqual(searchModels(models, '实验-3,实验-5').map(m => m.id), ['model-3', 'model-5'])
  assert.deepEqual(searchModels(models, '', 'workflow-1'), [models[1]])
  assert.deepEqual(searchModels(models, 'missing'), [])
  assert.equal(workflowPage(searchModels(models, 'quadmix 随机'), 2).items.length, 5)
  assert.equal(workflowPage(models, 3).items.length, 2)
})

test('selections persist across searches and pages without duplicate IDs', () => {
  const selected = []
  selectModel(selected, workflowPage(models, 1).items[0].id, true)
  selectModel(selected, workflowPage(models, 2).items[0].id, true)
  selectModel(selected, searchModels(models, '实验-9')[0].id, true)
  selectModel(selected, models[0].id, true)
  assert.deepEqual(selected, ['model-0', 'model-5', 'model-9'])
  selectModel(selected, 'model-5', false)
  assert.deepEqual(selected, ['model-0', 'model-9'])
  assert.equal(workflowPage([], 3).page, 1)
})

test('training defaults are visible and editable independently, including copied legacy settings', () => {
  const a = createStrategy(), b = createStrategy('manual')
  a.trainingOverrides.token_budget = 15
  assert.equal(b.trainingOverrides.token_budget, 401395843)
  const copied = copyWorkflow({ resources: {}, strategies: [{ type: 'random' }],
    training: { token_budget: 1234, device_batch_size: 2 }, evaluation: { datasets: [] } })
  assert.equal(copied.strategies[0].trainingOverrides.token_budget, 1234)
  assert.equal(copied.strategies[0].trainingOverrides.device_batch_size, 2)
  const ui = readFileSync(new URL('./components/steps/TrainingConfigStep.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(ui, /type="checkbox"|v-if="Object\.keys\(strategy\.trainingOverrides/)
})

test('title and four-step navigation share one sticky container', () => {
  const app = readFileSync(new URL('./App.vue', import.meta.url), 'utf8')
  assert.match(app, /class="workspace-header">[\s\S]*?<header[\s\S]*?<StepNavigation[^>]*\/>\s*<\/div>/)
  assert.equal((app.match(/<StepNavigation/g) || []).length, 1)
})
