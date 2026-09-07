<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { apiRequest } from '../api'
import { hasProgress } from '../workflow-state'
const props = defineProps({ selectedId: { type: String, default: '' } })
const emit = defineEmits(['select', 'copy'])
const workflows = ref([])
const error = ref('')
const credential = ref('')
const selected = computed(() => workflows.value.find(w => w.id === props.selectedId))
let timer
function state(w) {
  if (w.status === 'SUCCEEDED') return '已完成'
  if (w.status === 'FAILED') return '终止（失败）'
  if (w.status === 'NEEDS_ATTENTION') return '待人工核对'
  if (w.status === 'WAITING_AUTH') return '等待授权'
  return '正在作业'
}
async function load() {
  try { workflows.value = await apiRequest('workflows'); error.value = '' }
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
  <section class="step-panel">
    <h2>{{ selectedId ? '实验作业详情' : '实验作业' }}</h2>
    <p v-if="error" class="error-message">{{ error }}</p>
    <template v-if="!selectedId">
      <p>每条实验包含配比采样、训练评测两个阶段。复制配置不会立即提交新作业。</p>
      <article v-for="w in workflows" :key="w.id" class="workflow-card">
        <header><strong>{{ w.name }}</strong><b>{{ state(w) }}</b></header>
        <p>{{ w.stage }}</p>
        <button type="button" class="button secondary" @click="emit('select', w.id)">查看作业详情</button>
        <button type="button" class="button secondary" @click="copy(w.id)">复制并调整参数</button>
      </article>
      <p v-if="!workflows.length && !error">暂无实验作业。</p>
    </template>
    <template v-else>
      <button type="button" class="button secondary" @click="emit('select', '')">返回实验作业</button>
      <article v-if="selected" class="workflow-card">
        <h3>{{ selected.name }} · {{ state(selected) }}</h3>
        <p>{{ selected.stage }}</p>
        <template v-if="!error && hasProgress(selected)">
          <b>阶段进度 {{ selected.progress }}%</b>
          <div class="progress-track"><span :style="{width: `${selected.progress}%`}"></span></div>
        </template>
        <p v-if="selected.message" class="error-message">{{ selected.message }}</p>
        <div class="job-grid"><div v-for="job in selected.jobs" :key="job.name">
          <strong>{{ job.name }}</strong><small>{{ job.status }} · {{ job.id || '尚未创建' }}</small>
          <a v-if="job.url" :href="job.url" target="_blank" rel="noopener noreferrer">打开 ModelArts 作业详情</a>
        </div></div>
        <div class="output-paths"><span>配比结果：{{ selected.outputs.mixing }}</span><span>采样集：{{ selected.outputs.sampled }}</span><span>训练结果：{{ selected.outputs.training }}</span></div>
        <button type="button" class="button secondary" @click="copy(selected.id)">复制并调整参数</button>
        <label class="field"><span>更新身份认证凭据</span><input v-model="credential" type="password" autocomplete="off" /></label>
        <button type="button" class="button secondary" @click="renew">更新此实验凭据</button>
      </article>
      <p v-else-if="!error">正在加载作业详情…</p>
    </template>
  </section>
</template>
