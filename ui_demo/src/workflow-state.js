export const fieldLabels = {
  url: 'url', endpoint: 'url', region: 'region',
  Authorization: 'Authorization', authorization: 'Authorization', workspace_id: 'workspace_id',
  workspace_name: 'workspaceName',
  image_url: 'image_url', image_repo_id: 'image_repo_id', flavor_id: 'flavor_id', pool_id: 'pool_id',
}
export function hasProgress(workflow) {
  return Boolean(workflow.jobs?.some(job => job.id)) &&
    !['FAILED', 'NEEDS_ATTENTION', 'WAITING_AUTH'].includes(workflow.status) && !workflow.message
}
export function submissionFailed(workflow) {
  return ['FAILED', 'NEEDS_ATTENTION'].includes(workflow.status)
}
