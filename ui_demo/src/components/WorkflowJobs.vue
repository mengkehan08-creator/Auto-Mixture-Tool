<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { apiRequest } from '../api'
import { newestWorkflows, searchWorkflows, statusView, stageIndex, workflowStages } from '../workflow-state'
import WorkflowProgress from './WorkflowProgress.vue'
const props = defineProps({ selectedId: { type: String, default: '' } })
const emit = defineEmits(['select', 'copy'])
const workflows = ref([])
const search = ref('')
const filteredWorkflows = computed(() => searchWorkflows(workflows.value, search.value))
const error = ref('')
const credential = ref('')
const deleteDialog = ref(null)
const deleteTarget = ref(null)
const deleting = ref(false)
const deleteError = ref('')
const confirmedNotCreated = ref(false)
const needsAbsenceConfirmation = computed(() => deleteTarget.value &&
  ['NEEDS_ATTENTION', 'DELETE_FAILED'].includes(deleteTarget.value.status) &&
  !deleteTarget.value.jobs?.some(job => job.id) &&
  deleteTarget.value.jobs?.some(job => job.status === 'SUBMITTING'))
const hasRemoteJob = computed(() => Boolean(deleteTarget.value?.jobs?.some(job => job.id)))
const selected = computed(() => workflows.value.find(w => w.id === props.selectedId))
let timer
function createdTime(w) {
  const date = new Date(w.created_at)
  return Number.isNaN(date.getTime()) ? '创建时间未记录' : date.toLocaleString('zh-CN', { hour12: false })
}
const counts = computed(() => ['active', 'success', 'danger', 'warning'].map(tone => ({
  tone, label: { active: '正在作业', success: '已完成', danger: '失败终止', warning: '待处理' }[tone],
  count: workflows.value.filter(w => statusView(w.status).tone === tone).length,
})))
async function load() {
  try {
    workflows.value = newestWorkflows(await apiRequest('workflows')); error.value = ''
    if (props.selectedId && !workflows.value.some(w => w.id === props.selectedId)) emit('select', '')
  }
  catch (reason) { error.value = reason.message }
}
async function copy(id) {
  try { emit('copy', await apiRequest(`workflows/${id}/configuration`)) }
  catch (reason) { error.value = reason.message }
}
function confirmDelete(workflow) {
  deleteTarget.value = workflow
  deleteError.value = ''
  confirmedNotCreated.value = false
  deleteDialog.value.showModal()
}
async function remove() {
  if (deleting.value || !deleteTarget.value || (needsAbsenceConfirmation.value && !confirmedNotCreated.value)) return
  deleting.value = true
  try {
    const confirmation = needsAbsenceConfirmation.value && confirmedNotCreated.value ? '?confirmed_not_created=true' : ''
    await apiRequest(`workflows/${deleteTarget.value.id}${confirmation}`, { method: 'DELETE' })
    deleteDialog.value.close()
    await load()
  } catch (reason) { deleteError.value = reason.message }
  finally { deleting.value = false }
}
async function renew() {
  try {
    await apiRequest(`workflows/${props.selectedId}/authorization`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ authorization: credential.value }),
    })
    credential.value = ''; await load()
  } catch (reason) { error.value = reason.message }
}
onMounted(() => { load(); timer = setInterval(load, 3000) })
onBeforeUnmount(() => clearInterval(timer))
</script>
<template>
  <section class="step-panel workflow-page">
    <div class="workflow-title"><div><h2>{{ selectedId ? '实验作业详情' : '实验作业' }}</h2>
      <p>{{ selectedId ? '查看阶段进度、运行状态与输出位置' : '按创建时间倒序排列，最新作业在最上方' }}</p></div>
      <span class="workflow-count">共 {{ workflows.length }} 条实验</span></div>
    <p v-if="error" class="error-message">{{ error }}</p>
    <template v-if="!selectedId">
      <div class="workflow-summary"><div v-for="item in counts" :key="item.tone" :class="`tone-${item.tone}`"><span>{{ item.label }}</span><strong>{{ item.count }}</strong></div></div>
      <div class="workflow-search">
        <label class="field"><span>搜索作业名</span><input v-model="search" type="search" placeholder="输入完整或部分作业名" @keydown.esc="search = ''" /></label>
        <button v-if="search" type="button" class="button secondary" @click="search = ''">清空搜索</button>
        <span role="status">显示 {{ filteredWorkflows.length }} / {{ workflows.length }} 条</span>
      </div>
      <article v-for="w in filteredWorkflows" :key="w.id" class="workflow-card">
        <header><div><strong>{{ w.name }}</strong><small>创建时间 · {{ createdTime(w) }}</small></div><span class="status-badge" :class="`tone-${statusView(w.status).tone}`">{{ statusView(w.status).label }}</span></header>
        <p class="workflow-stage-caption">{{ ['FAILED', 'NEEDS_ATTENTION', 'WAITING_AUTH', 'DELETING', 'DELETE_FAILED'].includes(w.status) ? statusView(w.status).label : `当前阶段：${workflowStages[stageIndex(w)]}` }}</p>
        <p v-if="w.status === 'DELETE_FAILED'" class="error-message">{{ w.message }}</p>
        <div class="workflow-actions">
        <button type="button" class="button secondary" @click="emit('select', w.id)">查看作业详情</button>
        <button type="button" class="button secondary" @click="copy(w.id)">复制并调整参数</button>
        <button type="button" class="button delete-workflow" :disabled="w.status === 'DELETING'" @click="confirmDelete(w)">{{ w.status === 'DELETE_FAILED' ? '重试删除' : '删除实验' }}</button>
        </div>
      </article>
      <p v-if="!workflows.length && !error">暂无实验作业。</p>
      <p v-else-if="!filteredWorkflows.length && !error" class="workflow-search-empty">没有匹配的实验作业，请更换关键词或清空搜索。</p>
    </template>
    <template v-else>
      <button type="button" class="button secondary" @click="emit('select', '')">返回实验作业</button>
      <article v-if="selected" class="workflow-card">
        <header><div><strong>{{ selected.name }}</strong><small>创建时间 · {{ createdTime(selected) }}</small></div><span class="status-badge" :class="`tone-${statusView(selected.status).tone}`">{{ statusView(selected.status).label }}</span></header>
        <WorkflowProgress :workflow="error ? { ...selected, message: error } : selected" />
        <p v-if="selected.message" class="error-message">{{ selected.message }}</p>
        <h3 class="workflow-section-title">关联作业</h3>
        <div class="job-grid"><div v-for="(job, index) in selected.jobs" :key="job.name">
          <div class="job-heading"><strong>{{ job.module === 'training-evaluation' ? '训练评测作业（旧版）' : ['配比采样作业', '模型训练作业', '模型评测作业'][index] }}</strong><span class="status-badge" :class="`tone-${statusView(job.status).tone}`">{{ statusView(job.status).label }}</span></div>
          <small>{{ job.name }}</small><small>作业 ID：{{ job.id || (job.status === 'SUBMITTING' ? '未返回，创建结果待核对' : '尚未创建') }}</small>
          <a v-if="job.url" :href="job.url" target="_blank" rel="noopener noreferrer">打开 ModelArts 作业详情</a>
        </div></div>
        <h3 class="workflow-section-title">输出位置</h3>
        <div class="output-paths"><span>配比结果：{{ selected.outputs?.mixing }}</span><span>采样集：{{ selected.outputs?.sampled }}</span><span>模型输出：{{ selected.outputs?.models || selected.outputs?.training }}</span><span>评测与对比报告：{{ selected.outputs?.reports || selected.outputs?.training }}</span></div>
        <button type="button" class="button secondary" @click="copy(selected.id)">复制并调整参数</button>
        <button type="button" class="button delete-workflow" :disabled="selected.status === 'DELETING'" @click="confirmDelete(selected)">{{ selected.status === 'DELETE_FAILED' ? '重试删除' : '删除实验' }}</button>
        <label class="field"><span>更新身份认证凭据</span><input v-model="credential" type="password" autocomplete="off" /></label>
        <button type="button" class="button secondary" @click="renew">更新此实验凭据</button>
      </article>
      <p v-else-if="!error">正在加载作业详情…</p>
    </template>
    <dialog ref="deleteDialog" class="delete-dialog" aria-labelledby="delete-title" @cancel="deleting && $event.preventDefault()">
      <h3 id="delete-title">确认删除实验？</h3>
      <p class="delete-name">{{ deleteTarget?.name }}</p>
      <p v-if="hasRemoteJob">正在运行或排队的关联作业将被终止，确认结束后移除记录。</p>
      <p v-else-if="needsAbsenceConfirmation">提交结果不明确，未收到作业 ID。请先在 ModelArts 核对；确认未创建作业后，仅删除工具记录，不发送终止请求。</p>
      <p v-else>未创建远程作业时直接删除记录；如有正在进行的提交请求，会等待其结果再处理。</p>
      <label v-if="needsAbsenceConfirmation" class="absence-confirmation"><input v-model="confirmedNotCreated" type="checkbox" :disabled="deleting" />我已在 ModelArts 核对，确认未创建该实验的远程作业</label>
      <p>后续作业不再自动提交。OBS 中的数据、模型和报告不会删除。</p>
      <p v-if="deleteError" class="error-message" role="alert">{{ deleteError }}</p>
      <div class="workflow-actions">
        <button type="button" autofocus class="button secondary" :disabled="deleting" @click="deleteDialog.close()">取消</button>
        <button type="button" class="button delete-workflow" :disabled="deleting || (needsAbsenceConfirmation && !confirmedNotCreated)" @click="remove">{{ deleting ? '正在处理…' : hasRemoteJob ? '确认删除并终止作业' : '确认删除记录' }}</button>
      </div>
    </dialog>
  </section>
</template>
