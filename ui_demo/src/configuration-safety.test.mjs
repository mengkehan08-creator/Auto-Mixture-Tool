import test from 'node:test'
import assert from 'node:assert/strict'
import { refreshJobCommands } from './job-commands.js'
import { repeatEstimate } from './budget-estimates.js'
import { readFileSync } from 'node:fs'
const source = file => readFileSync(new URL(file, import.meta.url), 'utf8')
test('final sample size is not inferred from proxy compute consumption', () => {
  const quad = source('./components/strategy/QuadMixConfig.vue')
  assert.doesNotMatch(quad, /proxyTokens|全部实验约/)
  assert.match(quad, /待统计/)
  assert.match(quad, /本次最终输出文本经训练 Tokenizer/)
  assert.doesNotMatch(quad, /1\.8 亿|历史参考/)
  assert.doesNotMatch(source('./components/ResourceGuide.vue'), /1\.8 亿|历史参考/)
})

test('strategy guides explain decisions before optional technical details', () => {
  const guide = source('./components/ResourceGuide.vue')
  for (const heading of ['怎么选数据', '适合什么情况', '最后得到什么', '使用前知道这件事']) assert.ok(guide.includes(heading))
  assert.match(guide, /<details v-else class="guide-details"/)
  assert.match(guide, /不代表每个领域各占相同份额/)
  assert.match(guide, /不保证优于人工或随机策略/)
})
test('unknown sampling size never becomes a made-up repetition estimate', () => {
  assert.equal(repeatEstimate(401395843, undefined), null)
  assert.equal(repeatEstimate(100, 0), null)
  assert.equal(repeatEstimate(400, 40), 10)
})
test('automatic commands refresh but manual and deliberately cleared commands are preserved', () => {
  const old = { mixing: 'old mix', training: 'old train', evaluation: 'old eval' }
  const runtime = { commands: { ...old }, autoCommandDefaults: old }
  const strategies = [{ mixingCommand: 'old mix', trainingCommand: 'my training' }, { mixingCommand: '', trainingCommand: null }]
  const next = { mixing: 'new mix', training: 'new train', evaluation: 'new eval' }
  refreshJobCommands(strategies, runtime, next)
  assert.equal(strategies[0].mixingCommand, 'new mix')
  assert.equal(strategies[0].trainingCommand, 'my training')
  assert.equal(strategies[1].mixingCommand, '')
  assert.equal(strategies[1].trainingCommand, 'new train')
  assert.equal(runtime.commands.evaluation, 'new eval')
})
test('retry and reset require confirmation before mutation or submission', () => {
  for (const file of ['./components/ParallelJobRetry.vue', './components/StageRetryPanel.vue']) {
    assert.match(source(file), /if \(confirmed !== true\)/)
    assert.match(source(file), /<ConfirmationDialog v-if="confirming"/)
  }
  assert.match(source('./App.vue'), /<ConfirmationDialog v-if="resetVisible"/)
  assert.match(source('./App.vue'), /Object.keys\(target\)/)
})
test('validation is invalidated when the address changes and stale responses are ignored', () => {
  const check = source('./components/ResourceCheck.vue')
  assert.match(check, /watch\(\(\) => props.uri/)
  assert.match(check, /current === version/)
})
