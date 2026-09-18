import { formatTokens, formatBillions, samplingFields } from './budget-estimates.js'

const missing = '未记录'
const count = value => Number.isFinite(value) ? formatTokens(value) : missing
const tokens = value => Number.isFinite(value) ? `${formatTokens(value)}（${formatBillions(value)}）` : missing

export function modelDetailRows(model) {
  const config = model.experiment_config || {}, sampling = model.sampling || {}
  const types = { quadmix: 'QuaDMix 算法', manual: '自定义配比', random: '随机配比' }
  const rows = [{ label: '配比策略', value: types[config.type] || config.type || missing }]
  if (config.type === 'quadmix') {
    rows.push({ label: '代理实验数', value: count(config.proxy_experiments) },
      { label: '代理实验步数（每组）', value: count(config.proxy_steps) })
    for (const field of samplingFields) {
      const range = config.sampling_bounds?.[field.key]
      rows.push({ label: `${field.label}（搜索范围）`, value: Array.isArray(range) && range.length === 2 && range.every(Number.isFinite)
        ? (range[0] === range[1] ? `${range[0]}（固定值）` : `${range[0]} ～ ${range[1]}`) : missing })
    }
  }
  rows.push({ label: '训练 Token 预算', value: tokens(model.training?.token_budget) },
    { label: '采样 Token 数（报告记录）', value: tokens(sampling.tokens) },
    { label: '训练文档数', value: count(sampling.train_docs) })
  return rows
}

export function domainTokenShares(model) {
  const sampling = model.sampling || {}
  const aliases = { math: '数学', mathematics: '数学', chemistry: '化学', biology: '生物学', physics: '物理' }
  return Object.entries(sampling.domain_token_ratios_named || sampling.domain_ratios || {})
    .filter(([, value]) => Number.isFinite(value) && value >= 0 && value <= 1)
    .map(([name, value]) => ({ name: aliases[name.toLowerCase()] || (/^\d+$/.test(name) ? `领域 ${name}（名称未记录）` : name), value }))
}

export function domainTokenSummary(model) {
  return domainTokenShares(model).map(({ name, value }) => `${name} ${(value * 100).toFixed(2)}%`).join(' · ') || '未记录'
}
