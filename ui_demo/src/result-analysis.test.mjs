import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('analysis has independent navigation, return path and list/detail entries', () => {
  const app = readFileSync(new URL('./App.vue', import.meta.url), 'utf8')
  const jobs = readFileSync(new URL('./components/WorkflowJobs.vue', import.meta.url), 'utf8')
  assert.match(app, /<ResultAnalysis v-if="page === 'analysis'"/)
  assert.match(app, /@analysis="navigate\('analysis'/)
  assert.equal((jobs.match(/>结果分析<\/button>/g) || []).length, 2)
})

test('analysis charts use fixed percentage scale and render data without HTML injection', () => {
  const source = readFileSync(new URL('./components/ResultAnalysis.vue', import.meta.url), 'utf8')
  assert.match(source, /workflows\/\$\{props.workflowId\}\/analysis/)
  assert.match(source, /共同评测项/)
  assert.match(source, /0%<\/span><span>50%<\/span><span>100%/)
  assert.match(source, /role="alert"/)
  assert.match(source, /requestVersion/)
  assert.doesNotMatch(source, /v-html|https:\/\/cdn|Math.random/)
})
