export function repeatEstimate(budget, tokens) {
  const b = Number(budget), t = Number(tokens)
  return b > 0 && t > 0 && Number.isFinite(b) && Number.isFinite(t) ? b / t : null
}

export const defaultSamplingBounds = () => ({ omega: [0, 0.1], epsilon: [0, 0.001], lambda: [0, 1000], eta: [0, 1] })
export const samplingFields = [
  { key: 'omega', label: 'ω · 质量排名范围', step: 0.01, max: 1, help: '排名 r ≤ ω 的文本优先选取。扩大范围通常增加采样量；不是原始质量分的上限。' },
  { key: 'epsilon', label: 'ε · 尾部采样率', step: 0.0001, max: 1, help: '非优先区域的基础入选概率。提高 ε 会增加尾部数据；0 表示不选尾部。' },
  { key: 'lambda', label: 'λ · 选取曲线陡峭度', step: 10, help: '控制优先区域的选取强度。其他参数固定时，提高 λ 通常增加重复入选的强度。' },
  { key: 'eta', label: 'η · 强度指数', step: 0.1, max: 1, help: '放大优先区域的选取强度。其他参数固定时，提高 η 通常增加入选次数，不代表增加唯一文档。' },
]
export function validBounds(bounds) {
  return samplingFields.every(({ key, max }) => {
    const pair = bounds?.[key]
    return Array.isArray(pair) && pair.length === 2 && pair.every(n => typeof n === 'number' && Number.isFinite(n)) && pair[0] >= 0 && pair[1] >= pair[0] && (max === undefined || pair[1] <= max)
  })
}
export function proxyTrainingTokens(steps) {
  return Number.isInteger(steps) && steps > 0 ? steps * 8 * 2048 : null
}
export function formatTokens(tokens) {
  return Number.isFinite(tokens) ? Math.round(tokens).toLocaleString('en-US') : '待统计'
}
export function formatBillions(tokens) {
  if (!Number.isFinite(tokens) || tokens < 0) return '待统计'
  if (tokens > 0 && tokens < 1000000) return '<0.001 B Token'
  return `${(tokens / 1e9).toFixed(3)} B Token`
}
// Approximate the token-weighted rank integral of the sampling function.
// This is a scenario before filters/trim, not a prediction of searched parameters.
function samplingFraction({ omega, epsilon, lambda, eta }) {
  let sum = 0
  for (let i = 0; i < 128; i++) {
    const rank = omega * (i + 0.5) / 128
    sum += (2 / (1 + Math.exp(-lambda * (omega - rank)))) ** eta
  }
  return epsilon + omega * sum / 128
}
export function sampleScenario(total, bounds) {
  if (!(total > 0) || !Number.isFinite(total) || !validBounds(bounds)) return null
  const point = selector => Object.fromEntries(samplingFields.map(({ key }) => [key, selector(bounds[key])]))
  return {
    low: total * samplingFraction(point(p => p[0])),
    midpoint: total * samplingFraction(point(p => (p[0] + p[1]) / 2)),
    high: total * samplingFraction(point(p => p[1])),
  }
}
export function samplingRisk(budget, scenario) {
  const estimated = repeatEstimate(budget, scenario?.midpoint)
  if (estimated !== null) return { ratio: estimated, warning: estimated > 3, basis: '参数范围中点情景估算，非最终采样结果' }
  return { ratio: null, warning: Number(budget) > 0 && scenario?.high === 0, basis: '采样量未知或当前范围预计无数据' }
}
