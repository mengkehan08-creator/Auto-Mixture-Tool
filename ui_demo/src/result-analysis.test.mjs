import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { scoreRanking, formatScore } from './result-scores.js'

test('analysis has independent navigation, return path and list/detail entries', () => {
  const app = readFileSync(new URL('./App.vue', import.meta.url), 'utf8')
  const jobs = readFileSync(new URL('./components/WorkflowJobs.vue', import.meta.url), 'utf8')
  assert.match(app, /<ResultAnalysis v-if="page === 'analysis'"/)
  assert.match(app, /@analysis="navigate\('analysis'/)
  assert.equal((jobs.match(/<span>结果分析<\/span>/g) || []).length, 2)
  assert.equal((jobs.match(/class="button analysis-entry"/g) || []).length, 2)
  assert.match(jobs, /workflow-header-actions/)
})

test('analysis charts use fixed percentage scale and render data without HTML injection', () => {
  const source = readFileSync(new URL('./components/ResultAnalysis.vue', import.meta.url), 'utf8')
  assert.match(source, /workflows\/\$\{props.workflowId\}\/analysis/)
  assert.match(source, /共同评测项/)
  const chart = readFileSync(new URL('./components/ScoreComparisonChart.vue', import.meta.url), 'utf8')
  assert.match(chart, /\[0, .25, .5, .75, 1\]/)
  assert.match(chart, /<rect /)
  assert.match(chart, /<line /)
  assert.doesNotMatch(chart, /v-html|https:\/\/cdn/)
  assert.match(source, /role="alert"/)
  assert.match(source, /requestVersion/)
  assert.doesNotMatch(source, /v-html|https:\/\/cdn|Math.random/)
})

test('ranking marks every tied maximum and excludes null, NaN and Infinity', () => {
  const models = [0, .8, .8, null, NaN, Infinity].map((value, id) => ({ id, value }))
  assert.deepEqual(scoreRanking(models, model => model.value), { ids: [1, 2], label: '并列最高' })
  assert.deepEqual(scoreRanking(models.slice(3), model => model.value), { ids: [], label: '' })
  assert.deepEqual(scoreRanking([{ id: 'zero', value: 0 }], model => model.value), { ids: ['zero'], label: '最高' })
})

test('negative centered scores, raw precision and near-equality use correct ranking', () => {
  assert.deepEqual(scoreRanking([{ id: 'a', value: -.3 }, { id: 'b', value: -.1 }], m => m.value).ids, ['b'])
  assert.deepEqual(scoreRanking([{ id: 'a', value: .800001 }, { id: 'b', value: .800002 }], m => m.value).ids, ['b'])
  assert.deepEqual(scoreRanking([{ id: 'a', value: .8 }, { id: 'b', value: .8 + 1e-10 }], m => m.value).ids, ['a', 'b'])
})

test('accuracy uses percentages and centered uses decimal scores without unit mixing', () => {
  assert.equal(formatScore(.7356), '73.56%')
  assert.equal(formatScore(.7356, 'centered'), '0.7356')
  assert.equal(formatScore(-.1, 'centered'), '-0.1000')
  assert.equal(formatScore(null), '未提供')
  assert.equal(formatScore(NaN), '未提供')
  assert.equal(formatScore(0), '0.00%')
})

test('all comparison views share best-score component and narrative renders structured text', () => {
  const source = readFileSync(new URL('./components/ResultAnalysis.vue', import.meta.url), 'utf8')
  assert.equal((source.match(/<AnalysisScore /g) || []).length, 4)
  assert.equal((source.match(/<ScoreComparisonChart /g) || []).length, 2)
  assert.match(source, /conclusion_parts/)
  assert.match(source, /'conclusion-best': part.best/)
  assert.match(source, /\.bar-best .analysis-track > span/)
  const score = readFileSync(new URL('./components/AnalysisScore.vue', import.meta.url), 'utf8')
  assert.match(score, /#bb2737/)
  assert.match(score, /score-badge/)
})
