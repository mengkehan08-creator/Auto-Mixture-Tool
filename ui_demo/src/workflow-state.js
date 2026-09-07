export const fieldLabels = {
  url: '创建训练作业接口地址', endpoint: '创建训练作业接口地址', region: '区域',
  Authorization: '身份认证凭据', authorization: '身份认证凭据', workspace_id: '工作空间编号',
  workspace_name: '工作空间名称（用于任务网页链接，可选）',
  image_url: '训练镜像地址', image_repo_id: '镜像仓库编号', flavor_id: '资源规格编号', pool_id: '资源池编号',
}
export function hasProgress(workflow) {
  return Boolean(workflow.jobs?.some(job => job.id)) &&
    !['FAILED', 'NEEDS_ATTENTION', 'WAITING_AUTH'].includes(workflow.status) && !workflow.message
}
export function submissionFailed(workflow) {
  return ['FAILED', 'NEEDS_ATTENTION'].includes(workflow.status)
}
