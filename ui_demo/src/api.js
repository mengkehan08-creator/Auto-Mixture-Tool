// Keep requests under the same proxy prefix as /ui or /ui/.
export function apiUrl(path, location = window.location) {
  const prefix = location.pathname.replace(/\/ui\/?$/, '').replace(/\/$/, '')
  return `${prefix}/api/v1/${path.replace(/^\//, '')}`
}

export async function apiRequest(path, options = {}) {
  if (window.location.protocol === 'file:') {
    throw new Error('请通过正在运行的服务访问 /ui，不能从本地 HTML 文件提交作业。')
  }
  const response = await fetch(apiUrl(path), options)
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    throw new Error(`服务返回非 JSON 响应（HTTP ${response.status}）。请检查代理路径或登录状态。`)
  }
  const value = await response.json()
  if (!response.ok) {
    const detail = value.detail || '请求失败'
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return value
}
