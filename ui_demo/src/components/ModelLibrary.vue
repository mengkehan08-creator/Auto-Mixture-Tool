<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiRequest } from '../api'
import { workflowPage } from '../workflow-state'
import { searchModels, selectModel } from '../model-selection'
const props = defineProps({ selected: { type: Array, default: null }, workflowId: String })
const entries = ref([])
const error = ref('')
const search = ref('')
const currentPage = ref(1)
const filtered = computed(() => searchModels(entries.value, search.value, props.workflowId))
const pagination = computed(() => workflowPage(filtered.value, currentPage.value))
const selectedModels = computed(() => (props.selected || []).map(id => entries.value.find(m => m.id === id) || { id, name: id }))
watch([search, () => props.workflowId], () => { currentPage.value = 1 }, { flush: 'sync' })
watch(() => pagination.value.pageCount, count => { currentPage.value = Math.min(currentPage.value, count) })
async function load() {
  try { entries.value = await apiRequest('models'); error.value = '' }
  catch (reason) { error.value = reason.message }
}
function toggle(id, checked) {
  selectModel(props.selected, id, checked)
}
onMounted(load)
</script>
<template>
  <section class="config-block model-library">
    <div class="section-title-row"><h3>{{ selected ? '加入历史模型对比' : '训练成功的模型' }}</h3><button type="button" class="button secondary" @click="load">刷新模型</button></div>
    <p v-if="selected">本次训练的全部模型自动加入评测；还可选择其他实验的成功模型，无需重新训练。</p>
    <label class="field"><span>搜索模型或来源实验</span><input v-model="search" type="search" placeholder="多个关键词用空格或逗号分隔，匹配任意关键词" @keydown.esc="search = ''" /></label>
    <div v-if="selected" class="selected-models">
      <strong role="status">已选择 {{ selected.length }} 个历史模型</strong>
      <div class="model-chips"><button v-for="model in selectedModels" :key="model.id" type="button" :aria-label="`移除模型 ${model.name}`" @click="toggle(model.id, false)">{{ model.name }} ×</button></div>
    </div>
    <p v-if="error" class="error-message">{{ error }}</p>
    <article v-for="model in pagination.items" :key="model.id" class="model-entry">
      <label class="model-title"><input v-if="selected" type="checkbox" :checked="selected.includes(model.id)" @change="toggle(model.id, $event.target.checked)" /><strong>{{ model.name }}</strong><span class="status-badge tone-success">训练成功</span></label>
      <small>{{ model.workflow_name }} · {{ model.strategy_name }} · {{ model.nodes }} 节点</small>
      <details><summary>查看模型参数与保存地址</summary>
        <p class="break-path">模型 ID：{{ model.id }}</p><p class="break-path">{{ model.obs_uri }}</p>
        <small>{{ model.metadata_source }}</small><pre>{{ JSON.stringify(model.training_config, null, 2) }}</pre>
      </details>
    </article>
    <p v-if="!filtered.length && !error">暂无符合条件的成功模型。</p>
    <nav v-if="filtered.length" class="workflow-pagination" aria-label="历史模型分页">
      <span role="status">共 {{ filtered.length }} 个 · 每页 5 个 · 第 {{ pagination.page }} / {{ pagination.pageCount }} 页</span>
      <div><button class="button secondary" type="button" :disabled="pagination.page === 1" @click="currentPage = pagination.page - 1">上一页</button><button class="button secondary" type="button" :disabled="pagination.page === pagination.pageCount" @click="currentPage = pagination.page + 1">下一页</button></div>
    </nav>
    <p v-if="selected?.some(id => !entries.some(m => m.id === id))" class="error-message">存在不可用的历史模型，请刷新并重新选择。<button type="button" class="button secondary" @click="selected.splice(0)">清空选择</button></p>
  </section>
</template>
<style scoped>
.model-entry { padding: 14px; margin: 10px 0; border: 1px solid #e1e7f3; background: #f8faff; border-radius: 10px; }
.model-title { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.model-title input[type="checkbox"] { width: 16px; height: 16px; padding: 0; flex-shrink: 0; accent-color: #5277df; }
.selected-models { margin: 14px 0; color: #526583; font-size: 12px; }
.model-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.model-chips button { border: 1px solid #d4dff8; background: #edf3ff; color: #365fc3; border-radius: 8px; padding: 5px 10px; max-width: 100%; overflow-wrap: anywhere; }
small { display: block; margin: 8px 0; color: #71809a; }
summary { cursor: pointer; color: #486ce0; margin-top: 12px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
</style>
