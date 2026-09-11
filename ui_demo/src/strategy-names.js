export const strategyId = strategy => `${strategy.type}_${strategy.id}`

export function parameterName(strategy) {
  if (strategy.type === 'quadmix') return `ex-${strategy.proxyExperiments ?? 16}-${strategy.proxySteps ?? 15}`
  return `${strategy.type}-s${strategy.seed ?? 42}`
}

export const strategyLabel = strategy => strategy.name?.trim() || `${parameterName(strategy)} · 策略 ${strategy.id}`
export const strategyNameHint = strategy => `${parameterName(strategy)}-{提交时间}`

export function trainingNameHint(strategy) {
  const training = strategy.trainingOverrides || {}
  const budget = training.token_budget ? `t${training.token_budget}` : training.num_iterations ? `step${training.num_iterations}` : 'auto'
  return `train-${parameterName(strategy)}-${budget}-{提交时间}`
}
