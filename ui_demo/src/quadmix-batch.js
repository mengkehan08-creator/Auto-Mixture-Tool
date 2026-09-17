import { createStrategy } from './data/defaults.js'
import { defaultSamplingBounds, samplingFields, validBounds } from './budget-estimates.js'

export const batchExample = () => ({
  experiments: '100, 300, 500', steps: '5000', parameter: 'omega',
  mode: 'upper', values: '0.1, 0.15, 0.2, 0.25, 0.3',
})

function numbers(text, label, integer = false) {
  const parts = String(text).trim().split(/[\s,，;；]+/).filter(Boolean)
  if (!parts.length) throw new Error(`请填写${label}。`)
  const values = parts.map(Number)
  if (values.some(n => !Number.isFinite(n) || (integer ? !Number.isSafeInteger(n) || n < 1 : n < 0))) {
    throw new Error(`${label}必须为${integer ? '正整数' : '有限非负数'}，多个值用逗号分隔。`)
  }
  return [...new Set(values)]
}

export function planQuadMixBatch(source, settings) {
  if (source.type !== 'quadmix') throw new Error('批量配置仅适用于 QuaDMix 策略。')
  const bounds = source.samplingBounds || defaultSamplingBounds()
  if (!validBounds(bounds)) throw new Error('请先修正当前策略的参数搜索范围。')
  const field = samplingFields.find(f => f.key === settings.parameter)
  if (!field || !['upper', 'lower', 'fixed'].includes(settings.mode)) throw new Error('请选择有效的扫描参数和修改方式。')
  const experiments = numbers(settings.experiments, '代理实验数', true)
  const steps = numbers(settings.steps, '代理实验步数', true)
  const values = numbers(settings.values, '参数取值')
  if (experiments.length * steps.length * values.length > 1000) throw new Error('单次最多生成 1000 个组合，请减少取值或分批配置。')
  const rows = []
  for (const value of values) {
    const samplingBounds = JSON.parse(JSON.stringify(bounds))
    if (settings.mode === 'fixed') samplingBounds[field.key] = [value, value]
    else samplingBounds[field.key][settings.mode === 'lower' ? 0 : 1] = value
    if (!validBounds(samplingBounds)) {
      throw new Error(`${field.label.split(' · ')[0]} = ${value} 的范围无效：下限不能大于上限${field.max === undefined ? '。' : '，且上限不能超过 1。'}`)
    }
    for (const proxyExperiments of experiments) for (const proxySteps of steps) {
      rows.push({ key: `${value}:${proxyExperiments}:${proxySteps}`, proxyExperiments, proxySteps,
        samplingBounds: JSON.parse(JSON.stringify(samplingBounds)) })
    }
  }
  return rows
}

export function materializeQuadMixBatch(source, rows) {
  return rows.map(row => {
    const fresh = createStrategy('quadmix')
    return { ...fresh, ...JSON.parse(JSON.stringify(source)),
      // Each new strategy needs its own identity, auto-generated job names and model name.
      id: fresh.id, name: '', mixingJobName: '', trainingJobName: '', modelName: '',
      proxyExperiments: row.proxyExperiments, proxySteps: row.proxySteps,
      samplingBounds: JSON.parse(JSON.stringify(row.samplingBounds)),
    }
  })
}
