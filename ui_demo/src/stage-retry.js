import { normalizeEvaluationTasks } from './evaluation-selection.js'

export function retryDraft(config, defaults, workflow, stage) {
  const draft = structuredClone(config)
  delete draft.request_id
  draft.reuse = { workflow_id: workflow.id, stage }
  draft.commands = structuredClone(defaults.commands)
  draft.modelarts = { ...defaults.modelarts, ...draft.modelarts, authorization: '' }
  draft.evaluation.obs_packages ||= []
  draft.evaluation.datasets = normalizeEvaluationTasks(draft.evaluation.datasets)
  return draft
}

export function retryBody(draft) {
  const body = structuredClone(draft)
  for (const resource of body.offline_resources || []) {
    if (resource.role && resource.role in body.resources) resource.uri = body.resources[resource.role]
  }
  if (body.training.token_budget === '' || body.training.token_budget == null) delete body.training.token_budget
  return body
}
