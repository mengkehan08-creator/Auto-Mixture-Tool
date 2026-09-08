<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { apiRequest } from '../api'
import { newestWorkflows, statusView, stageIndex, workflowStages } from '../workflow-state'
import WorkflowProgress from './WorkflowProgress.vue'
const props = defineProps({ selectedId: { type: String, default: '' } })
const emit = defineEmits(['select', 'copy'])
const workflows = ref([])
const error = ref('')
const credential = ref('')
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
  try { workflows.value = newestWorkflows(await apiRequest('workflows')); error.value = '' }
  catch (reason) { error.value = reason.message }
}
async function copy(id) {
  try { emit('copy', await apiRequest(`workflows/${id}/configuration`)) }
  catch (reason) { error.value = reason.message }
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
      <article v-for="w in workflows" :key="w.id" class="workflow-card">
        <header><div><strong>{{ w.name }}</strong><small>创建时间 · {{ createdTime(w) }}</small></div><span class="status-badge" :class="`tone-${statusView(w.status).tone}`">{{ statusView(w.status).label }}</span></header>
        <p class="workflow-stage-caption">{{ ['FAILED', 'NEEDS_ATTENTION', 'WAITING_AUTH'].includes(w.status) ? statusView(w.status).label : `当前阶段：${workflowStages[stageIndex(w)]}` }}</p>
        <div class="workflow-actions">
        <button type="button" class="button secondary" @click="emit('select', w.id)">查看作业详情</button>
        <button type="button" class="button secondary" @click="copy(w.id)">复制并调整参数</button>
        </div>
      </article>
      <p v-if="!workflows.length && !error">暂无实验作业。</p>
    </template>
    <template v-else>
      <button type="button" class="button secondary" @click="emit('select', '')">返回实验作业</button>
      <article v-if="selected" class="workflow-card">
        <header><div><strong>{{ selected.name }}</strong><small>创建时间 · {{ createdTime(selected) }}</small></div><span class="status-badge" :class="`tone-${statusView(selected.status).tone}`">{{ statusView(selected.status).label }}</span></header>
        <WorkflowProgress :workflow="error ? { ...selected, message: error } : selected" />
        <p v-if="selected.message" class="error-message">{{ selected.message }}</p>
        <h3 class="workflow-section-title">关联作业</h3>
        <div class="job-grid"><div v-for="(job, index) in selected.jobs" :key="job.name">
          <div class="job-heading"><strong>{{ index === 0 ? '配比采样作业' : '训练评测作业' }}</strong><span class="status-badge" :class="`tone-${statusView(job.status).tone}`">{{ statusView(job.status).label }}</span></div>
          <small>{{ job.name }}</small><small>作业 ID：{{ job.id || '尚未创建' }}</small>
          <a v-if="job.url" :href="job.url" target="_blank" rel="noopener noreferrer">打开 ModelArts 作业详情</a>
        </div></div>
        <h3 class="workflow-section-title">输出位置</h3>
        <div class="output-paths"><span>配比结果：{{ selected.outputs?.mixing }}</span><span>采样集：{{ selected.outputs?.sampled }}</span><span>模型输出：{{ selected.outputs?.models || selected.outputs?.training }}</span><span>评测与对比报告：{{ selected.outputs?.reports || selected.outputs?.training }}</span></div>
        <button type="button" class="button secondary" @click="copy(selected.id)">复制并调整参数</button>
        <label class="field"><span>更新身份认证凭据</span><input v-model="credential" type="password" autocomplete="off" /></label>
        <button type="button" class="button secondary" @click="renew">更新此实验凭据</button>
      </article>
      <p v-else-if="!error">正在加载作业详情…</p>
    </template>
  </section>
</template>
