<script setup>
import { computed, onMounted, ref } from 'vue'
import { apiRequest } from '../api'
const props = defineProps({ selected: { type: Array, default: null }, workflowId: String })
const entries = ref([])
const error = ref('')
const search = ref('')
const filtered = computed(() => entries.value.filter(m => (!props.workflowId || m.workflow_id === props.workflowId) &&
  `${m.name} ${m.workflow_name}`.toLocaleLowerCase().includes(search.value.toLocaleLowerCase())))
async function load() {
  try { entries.value = await apiRequest('models'); error.value = '' }
  catch (reason) { error.value = reason.message }
}
function toggle(id, checked) {
  const index = props.selected.indexOf(id)
  if (checked && index < 0) props.selected.push(id)
  if (!checked && index >= 0) props.selected.splice(index, 1)
}
onMounted(load)
</script>
<template>
  <section class="config-block model-library">
    <div class="section-title-row"><h3>{{ selected ? '加入历史模型对比' : '训练成功的模型' }}</h3><button type="button" class="button secondary" @click="load">刷新模型</button></div>
    <p v-if="selected">本次训练的全部模型自动加入评测；还可选择其他实验的成功模型，无需重新训练。</p>
    <label class="field"><span>搜索模型或来源实验</span><input v-model="search" type="search" /></label>
    <p v-if="error" class="error-message">{{ error }}</p>
    <article v-for="model in filtered" :key="model.id" class="model-entry">
      <label class="model-title"><input v-if="selected" type="checkbox" :checked="selected.includes(model.id)" @change="toggle(model.id, $event.target.checked)" /><strong>{{ model.name }}</strong><span class="status-badge tone-success">训练成功</span></label>
      <small>{{ model.workflow_name }} · {{ model.strategy_name }} · {{ model.nodes }} 节点</small>
      <details><summary>查看模型参数与保存地址</summary>
        <p class="break-path">模型 ID：{{ model.id }}</p><p class="break-path">{{ model.obs_uri }}</p>
        <small>{{ model.metadata_source }}</small><pre>{{ JSON.stringify(model.training_config, null, 2) }}</pre>
      </details>
    </article>
    <p v-if="!filtered.length && !error">暂无符合条件的成功模型。</p>
    <p v-if="selected?.some(id => !entries.some(m => m.id === id))" class="error-message">存在不可用的历史模型，请刷新并重新选择。<button type="button" class="button secondary" @click="selected.splice(0)">清空选择</button></p>
  </section>
</template>
<style scoped>
.model-entry { padding: 14px; margin: 10px 0; border: 1px solid #e1e7f3; background: #f8faff; border-radius: 10px; }
.model-title { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
small { display: block; margin: 8px 0; color: #71809a; }
summary { cursor: pointer; color: #486ce0; margin-top: 12px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
</style>
