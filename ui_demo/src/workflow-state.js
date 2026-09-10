export const fieldLabels = {
  url: 'url', endpoint: 'url', region: 'region',
  Authorization: 'Authorization', authorization: 'Authorization', workspace_id: 'workspace_id',
  workspace_name: 'workspaceName',
  image_url: 'image_url', image_repo_id: 'image_repo_id', flavor_id: 'flavor_id', pool_id: 'pool_id',
}
export function hasProgress(workflow) {
  return Boolean(workflow.jobs?.some(job => job.id)) &&
    !['FAILED', 'NEEDS_ATTENTION', 'WAITING_AUTH', 'DELETING', 'DELETE_FAILED', 'DELETED'].includes(workflow.status) && !workflow.message
}
export function submissionFailed(workflow) {
  return ['FAILED', 'NEEDS_ATTENTION'].includes(workflow.status)
}

export function canRestart(workflow, stage) {
  if (!['training', 'evaluation'].includes(stage)) return false
  const count = stage === 'training' ? 1 : 2
  return workflow.pipeline_version === 3 && !workflow.delete_requested &&
    ['FAILED', 'SUCCEEDED'].includes(workflow.status) &&
    workflow.jobs?.slice(0, count).length === count &&
    workflow.jobs.slice(0, count).every(job => job.status === 'SUCCEEDED')
}

export function statusView(status = '') {
  const key = status.toUpperCase()
  if (key === 'DELETING') return { label: '正在终止并删除', tone: 'warning' }
  if (key === 'DELETE_FAILED') return { label: '删除未完成', tone: 'danger' }
  if (['SUCCEEDED', 'SUCCESS', 'COMPLETED'].includes(key)) return { label: '已完成', tone: 'success' }
  if (key === 'FAILED') return { label: '失败终止', tone: 'danger' }
  if (key === 'BLOCKED') return { label: '前序未成功，未提交', tone: 'warning' }
  if (['CANCELED', 'CANCELLED', 'TERMINATED'].includes(key)) return { label: '已终止', tone: 'muted' }
  if (key === 'WAITING_AUTH') return { label: '等待授权', tone: 'warning' }
  if (key === 'NEEDS_ATTENTION') return { label: '待人工核对', tone: 'warning' }
  if (['QUEUED', 'PENDING', 'WAITING', 'SUBMITTED', 'CREATING'].includes(key)) return { label: '等待运行', tone: 'muted' }
  if (key === 'SUBMITTING') return { label: '正在提交', tone: 'active' }
  if (['RUNNING', 'MIXING_RUNNING', 'TRAINING_RUNNING', 'EVALUATION_RUNNING', 'TRAINING_SUCCEEDED', 'MIXING_SUCCEEDED'].includes(key)) return { label: '正在作业', tone: 'active' }
  return { label: '状态待确认', tone: 'muted' }
}

export function newestWorkflows(items) {
  const timestamp = w => Date.parse(w.created_at) || 0
  return [...items].sort((a, b) => timestamp(b) - timestamp(a))
}

export function searchWorkflows(items, query) {
  const keyword = query.trim().toLocaleLowerCase()
  return items.filter(item => !keyword || (item.name || '').toLocaleLowerCase().includes(keyword))
}

export function workflowStatusGroup(status = '') {
  const key = status.toUpperCase()
  const tone = statusView(key).tone
  if (tone === 'success') return 'success'
  if (tone === 'danger' || ['CANCELED', 'CANCELLED', 'TERMINATED'].includes(key)) return 'danger'
  if (tone === 'active' || ['QUEUED', 'PENDING', 'WAITING', 'SUBMITTED', 'CREATING'].includes(key)) return 'active'
  return 'warning'
}

export function workflowPage(items, requestedPage = 1) {
  const pageCount = Math.max(1, Math.ceil(items.length / 5))
  const page = Math.min(pageCount, Math.max(1, requestedPage))
  const offset = (page - 1) * 5
  return { page, pageCount, items: items.slice(offset, offset + 5),
    start: items.length ? offset + 1 : 0, end: Math.min(offset + 5, items.length) }
}

export const workflowStages = ['配比提交', '配比采样', '训练提交', '模型训练', '评测提交', '模型评测', '全部完成']

export function stageIndex(workflow) {
  if (workflow.status === 'SUCCEEDED') return 6
  if (workflow.pipeline_version === 4) {
    const evaluation = workflow.jobs.find(j => j.module === 'evaluation')
    if (evaluation?.id) return 5
    if (workflow.jobs.some(j => j.module === 'training' && j.id)) return 3
    if (workflow.jobs.some(j => j.module === 'mixing' && j.id)) return 1
    return 0
  }
  const evaluation = workflow.jobs?.[2]
  if (evaluation?.id) return ['active', 'success'].includes(statusView(evaluation.status).tone) ? 5 : 4
  if (workflow.status === 'TRAINING_SUCCEEDED') return 4
  const training = workflow.jobs?.[1]
  const mixing = workflow.jobs?.[0]
  if (workflow.status === 'TRAINING_RUNNING' || training?.id) {
    return statusView(training?.status).tone === 'active' || statusView(training?.status).tone === 'success' ? 3 : 2
  }
  if (workflow.status === 'MIXING_SUCCEEDED' || statusView(mixing?.status).tone === 'success') return 2
  if (workflow.status === 'MIXING_RUNNING' || mixing?.id) {
    return statusView(mixing?.status).tone === 'active' ? 1 : 0
  }
  return 0
}
