export function searchModels(models, query, workflowId) {
  const terms = query.trim().toLocaleLowerCase().split(/[\s,，;；]+/).filter(Boolean)
  return models.filter(model => (!workflowId || model.workflow_id === workflowId) &&
    (!terms.length || terms.some(term => `${model.name} ${model.workflow_name}`.toLocaleLowerCase().includes(term))))
}

export function selectModel(selected, id, checked) {
  const index = selected.indexOf(id)
  if (checked && index < 0) selected.push(id)
  if (!checked && index >= 0) selected.splice(index, 1)
}
