export const stemTasks = ['arc_easy', 'arc_challenge', 'mmlu_stem', 'gpqa_diamond', 'gsm8k_cot', 'math_cot_500']

export function normalizeEvaluationTasks(names) {
  return [...new Set(names.flatMap(name => name === 'stem' ? stemTasks : [name]))]
}
