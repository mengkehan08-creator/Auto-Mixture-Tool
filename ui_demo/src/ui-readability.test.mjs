import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('navigation and compact delete controls retain accessible labels', () => {
  assert.match(source('./components/StepNavigation.vue'), /:aria-current="currentStep === step.id \? 'step' : undefined"/)
  const strategy = source('./components/strategy/StrategyCard.vue')
  assert.match(strategy, /:aria-label="`删除策略 \$\{strategy.name\}`"/)
  assert.match(strategy, /:disabled="!removable"/)
})

test('training help belongs to the matching editable field and distinguishes final evaluation', () => {
  const training = source('./components/steps/TrainingConfigStep.vue')
  assert.match(training, /v-model.number="strategy.trainingOverrides\[field.key\]"/)
  assert.match(training, /:aria-describedby="`training-\$\{strategy.id\}-\$\{field.key\}`"/)
  assert.match(training, /:id="`training-\$\{strategy.id\}-\$\{field.key\}`"/)
  assert.match(training, /不影响训练后的独立评测/)
})

test('submission feedback remains explicit and pending submissions remain disabled', () => {
  const review = source('./components/steps/ReviewSubmitStep.vue')
  assert.match(review, /class="submission-actions" :aria-busy="status === 'loading'"/)
  assert.match(review, /class="success-message" role="status"/)
  assert.match(review, /v-if="error" class="error-message" role="alert"/)
  assert.match(review, /:disabled="status === 'loading' \|\|/)
  assert.match(source('./components/steps/EvaluationConfigStep.vue'), /尚未接入 · 当前不创建作业/)
})
