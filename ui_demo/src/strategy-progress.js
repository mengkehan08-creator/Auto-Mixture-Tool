const succeeded = status => ['SUCCEEDED', 'SUCCESS', 'COMPLETED'].includes(status)
const failed = status => ['FAILED', 'CANCELED', 'CANCELLED', 'TERMINATED'].includes(status)
const point = (label, state = 'waiting', detail = '待执行') => ({ label, state, detail })

function jobPoints(job, submitLabel, runLabel) {
  if (!job) return [point(submitLabel), point(runLabel)]
  const status = (job.status || '').toUpperCase()
  if (succeeded(status) && (job.id || job.reused)) {
    return [point(submitLabel, 'done', job.reused ? '复用前序输出' : '已提交'), point(runLabel, 'done', job.reused ? '已复用' : '已完成')]
  }
  const submit = job.id ? point(submitLabel, 'done', '已提交') :
    point(submitLabel, failed(status) ? 'error' : status === 'NEEDS_ATTENTION' ? 'blocked' : 'waiting',
      failed(status) ? '提交失败' : status === 'NEEDS_ATTENTION' ? '待人工核对' : status === 'SUBMITTING' ? '提交中' : '待提交')
  const run = !job.id ? point(runLabel, status === 'BLOCKED' ? 'blocked' : 'waiting', status === 'BLOCKED' ? '等待前序修复' : '待执行') :
    failed(status) ? point(runLabel, 'error', '失败或终止') :
    status === 'NEEDS_ATTENTION' ? point(runLabel, 'blocked', '待人工核对') :
    status === 'RUNNING' ? point(runLabel, 'running', '运行中') :
    point(runLabel, 'waiting', ['QUEUED', 'PENDING', 'WAITING', 'SUBMITTED', 'CREATING'].includes(status) ? '排队中' : '状态待确认')
  return [submit, run]
}

export function strategyProgress(workflow) {
  const jobs = workflow.jobs || []
  const ids = [...new Set(jobs.filter(j => j.module === 'mixing' || j.module === 'training').map(j => j.strategy_id))]
  const branches = ids.map(id => {
    const mixing = jobs.find(j => j.strategy_id === id && j.module === 'mixing')
    const training = jobs.find(j => j.strategy_id === id && j.module === 'training')
    return { id, name: mixing?.strategy_name || training?.strategy_name || id || '未命名策略',
      points: [...jobPoints(mixing, '配比提交', '配比采样'), ...jobPoints(training, '训练提交', '模型训练')] }
  })
  const completed = branches.filter(b => b.points.every(p => p.state === 'done')).length
  const merged = branches.length > 0 && completed === branches.length
  const hasError = branches.some(b => b.points.some(p => ['error', 'blocked'].includes(p.state)))
  const merge = point('训练汇合', merged ? 'done' : hasError ? 'blocked' : 'waiting', `${completed} / ${branches.length} 分支完成`)
  const evaluation = jobs.find(j => j.module === 'evaluation')
  const tail = [merge, ...(evaluation ? (merged ? jobPoints(evaluation, '评测提交', '模型评测') :
    [point('评测提交', hasError ? 'blocked' : 'waiting', '等待全部训练'), point('模型评测')]) : [])]
  const finished = succeeded(workflow.status) && tail.every(p => p.state === 'done')
  tail.push(point('全部完成', finished ? 'done' : 'waiting', finished ? '已完成' : '待完成'))
  const start = point('实验启动', jobs.some(j => j.id || (j.reused && succeeded(j.status))) ? 'done' : 'waiting', '按策略分支')
  if (workflow.statusUnavailable) {
    for (const p of [start, ...branches.flatMap(b => b.points), ...tail]) Object.assign(p, { state: 'waiting', detail: '状态暂不可用' })
  }
  return { branches, tail, start, completed: workflow.statusUnavailable ? 0 : completed, finished: finished && !workflow.statusUnavailable }
}
