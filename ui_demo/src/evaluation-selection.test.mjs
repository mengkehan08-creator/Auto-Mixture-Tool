import test from 'node:test'
import assert from 'node:assert/strict'
import { stemTasks, normalizeEvaluationTasks } from './evaluation-selection.js'
import { createEvaluationConfig } from './data/defaults.js'

test('default selects six individual STEM tasks without sharing mutable state', () => {
  const config = createEvaluationConfig()
  assert.equal(stemTasks.length, 6)
  assert.deepEqual(config.dataset.names, stemTasks)
  config.dataset.names.pop()
  assert.equal(createEvaluationConfig().dataset.names.length, 6)
})

test('legacy presets expand and submission removes duplicates without changing selection', () => {
  const input = ['stem', 'gsm8k_cot', 'stem']
  assert.deepEqual(normalizeEvaluationTasks(input), stemTasks)
  assert.deepEqual(input, ['stem', 'gsm8k_cot', 'stem'])
  assert.deepEqual(normalizeEvaluationTasks(['arc_easy', 'arc_easy']), ['arc_easy'])
  assert.deepEqual(normalizeEvaluationTasks([]), [])
  const partial = stemTasks.filter(name => name !== 'gsm8k_cot')
  assert.deepEqual(normalizeEvaluationTasks(partial), partial)
  assert.equal(normalizeEvaluationTasks([...partial, ...stemTasks]).length, 6)
})
