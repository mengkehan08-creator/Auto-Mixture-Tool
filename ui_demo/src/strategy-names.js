export const strategyId = strategy => `${strategy.type}_${strategy.id}`

export function parameterName(strategy) {
  if (strategy.type === 'quadmix') {
    const omega = Number(strategy.samplingBounds?.omega?.[1] ?? 0.1)
      .toLocaleString('en-US', { useGrouping: false, maximumSignificantDigits: 21 }).replace('.', 'p')
    return `ex-${strategy.proxyExperiments ?? 50}-${strategy.proxySteps ?? 15}-${omega}`
  }
  return `${strategy.type}-s${strategy.seed ?? 42}`
}

export const strategyLabel = strategy => strategy.name?.trim() || `${parameterName(strategy)} · 策略 ${strategy.id}`
export const strategyNameHint = strategy => `${parameterName(strategy)}-{提交时间}`

export function trainingNameHint(strategy) {
  const training = strategy.trainingOverrides || {}
  const budget = training.token_budget ? `t${training.token_budget}` : training.num_iterations ? `step${training.num_iterations}` : 'auto'
  return `train-${parameterName(strategy)}-${budget}-{提交时间}`
}
