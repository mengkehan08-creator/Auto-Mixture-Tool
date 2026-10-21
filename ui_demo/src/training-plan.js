export function trainingNodeCounts(strategies, training) {
  return [...new Set(strategies.length
    ? strategies.map(s => s.trainingNodesOverride ?? training.nodes)
    : [training.nodes])].sort((a, b) => a - b)
}

export function batchSizeMode(training) {
  return training.batch_size_mode ?? (training.total_batch_size != null ? 'fixed' : 'auto')
}
