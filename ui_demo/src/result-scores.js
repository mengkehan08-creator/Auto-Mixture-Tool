// Compare raw values within one metric; never rank rounded display strings.
export function scoreRanking(models, valueOf) {
  const valid = models.filter(model => Number.isFinite(valueOf(model)))
  if (!valid.length) return { ids: [], label: '' }
  const highest = Math.max(...valid.map(valueOf))
  const ids = valid.filter(model => Math.abs(valueOf(model) - highest) <= 1e-9).map(model => model.id)
  return { ids, label: ids.length > 1 ? '并列最高' : '最高' }
}

export function formatScore(value, metric = 'accuracy') {
  if (!Number.isFinite(value)) return '未提供'
  return metric === 'accuracy' ? `${(value * 100).toFixed(2)}%` : value.toFixed(4)
}
