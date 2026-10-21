export const stemTasks = ['arc_easy', 'arc_challenge', 'mmlu_stem', 'gpqa_diamond', 'gsm8k_cot', 'math_cot_500']

export function normalizeEvaluationTasks(names) {
  return [...new Set(names.flatMap(name => name === 'stem' ? stemTasks : [name]))]
}

const exclusivePresets = ['all', 'core']

export function toggleEvaluationTask(names, name) {
  const selected = normalizeEvaluationTasks(names)
  if (selected.includes(name)) return selected.filter(task => task !== name)
  if (exclusivePresets.includes(name)) return [name]
  return [...selected.filter(task => !exclusivePresets.includes(task)), name]
}

export function selectStemEvaluationTasks(names) {
  return normalizeEvaluationTasks([...names.filter(name => !exclusivePresets.includes(name)), ...stemTasks])
}
