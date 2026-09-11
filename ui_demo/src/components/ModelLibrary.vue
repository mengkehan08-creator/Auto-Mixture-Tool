<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { apiRequest } from '../api'
import { workflowPage } from '../workflow-state'
import { searchModels, selectModel, comparisonStatus, filterComparable } from '../model-selection'
const props = defineProps({ selected: { type: Array, default: null }, workflowId: String, reference: Object })
const entries = ref([])
const error = ref('')
const loading = ref(false)
const status = ref('compatible')
const statusLabels = { compatible: '同类型', different: '有差异' }
const tones = { compatible: 'tone-success', different: 'tone-danger' }
const parameterValue = value => value === null || value === undefined ? '未记录' : typeof value === 'object' ? JSON.stringify(value) : String(value)
let requestId = 0
let refreshTimer
const search = ref('')
const currentPage = ref(1)
const filtered = computed(() => searchModels(props.selected ? filterComparable(entries.value, status.value) : entries.value, search.value, props.workflowId))
const pagination = computed(() => workflowPage(filtered.value, currentPage.value))
const selectedModels = computed(() => (props.selected || []).map(id => entries.value.find(m => m.id === id) || { id, name: id }))
watch([search, status, () => props.workflowId], () => { currentPage.value = 1 }, { flush: 'sync' })
watch(() => pagination.value.pageCount, count => { currentPage.value = Math.min(currentPage.value, count) })
watch(() => props.reference, () => {
  requestId++
  loading.value = true
  clearTimeout(refreshTimer)
  refreshTimer = setTimeout(load, 350)
}, { deep: true })
async function load() {
  const current = ++requestId
  loading.value = true
  error.value = ''
  try {
    const result = props.selected ? await apiRequest('models/compare', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(props.reference) }) : await apiRequest('models')
    if (current === requestId) entries.value = result
  } catch (reason) { if (current === requestId) { error.value = reason.message; entries.value = [] } }
  finally { if (current === requestId) loading.value = false }
}
function toggle(id, checked) {
  if (checked && (loading.value || !entries.value.some(model => model.id === id))) return
  selectModel(props.selected, id, checked)
}
onMounted(load)
onBeforeUnmount(() => { requestId++; clearTimeout(refreshTimer) })
</script>
<template>
  <section class="config-block model-library">
    <div class="section-title-row"><h3>{{ selected ? '加入历史模型对比' : '训练成功的模型' }}</h3><button type="button" class="button secondary" :disabled="loading" @click="load">{{ loading ? '核对中…' : '刷新模型' }}</button></div>
    <p v-if="selected">两类模型均可选择。展开详情查看与本次配置的参数对比，节点数不参与差异判定。</p>
    <div v-if="selected" class="comparison-tabs" aria-label="模型类型筛选">
      <button v-for="(label, key) in statusLabels" :key="key" type="button" :class="{ active: status === key }" :aria-pressed="status === key" @click="status = key">{{ label }} <span>{{ filterComparable(entries, key).length }}</span></button>
    </div>
    <label class="field"><span>搜索模型或来源实验</span><input v-model="search" type="search" placeholder="多个关键词用空格或逗号分隔，匹配任意关键词" @keydown.esc="search = ''" /></label>
    <div v-if="selected" class="selected-models">
      <strong role="status">已选择 {{ selected.length }} 个历史模型</strong>
      <div class="model-chips"><button v-for="model in selectedModels" :key="model.id" type="button" :aria-label="`移除模型 ${model.name}`" @click="toggle(model.id, false)">{{ model.name }} ×</button></div>
    </div>
    <p v-if="error" class="error-message">{{ error }}</p>
    <p v-if="loading" role="status">正在读取模型清单，核对同类型条件…</p>
    <article v-for="model in pagination.items" :key="model.id" class="model-entry">
      <label class="model-title"><input v-if="selected" type="checkbox" :disabled="loading" :checked="selected.includes(model.id)" @change="toggle(model.id, $event.target.checked)" /><strong>{{ model.name }}</strong><span :class="['status-badge', selected ? tones[comparisonStatus(model)] : 'tone-success']">{{ selected ? statusLabels[comparisonStatus(model)] : '训练成功' }}</span></label>
      <small>{{ model.workflow_name }} · {{ model.strategy_name }} · {{ model.nodes }} 节点</small>
      <p v-if="selected && model.comparison?.reasons?.length" class="comparison-reasons">{{ model.comparison.reasons.join('；') }}</p>
      <details v-if="selected && model.comparison?.warnings?.length"><summary>对比注意事项 · {{ model.comparison.warnings.length }} 项</summary><ul><li v-for="warning in model.comparison.warnings" :key="warning">{{ warning }}</li></ul></details>
      <details><summary>查看模型参数与保存地址</summary>
        <p class="break-path">模型 ID：{{ model.id }}</p><p class="break-path">{{ model.obs_uri }}</p>
        <template v-if="selected && model.comparison?.parameters?.length">
          <p class="parameter-legend"><span class="parameter-same">● 参数相同</span><span class="parameter-different">● 参数不同或未记录</span></p>
          <div class="parameter-table"><table><thead><tr><th>参数</th><th>本次配置</th><th>历史模型</th><th>对比</th></tr></thead>
            <tbody><tr v-for="row in model.comparison.parameters" :key="row.key" :class="row.same ? 'parameter-same' : 'parameter-different'">
              <th scope="row">{{ row.label }}</th><td>{{ parameterValue(row.reference) }}</td><td>{{ parameterValue(row.candidate) }}</td><td>{{ row.missing ? '未记录' : row.same ? '相同' : '不同' }}</td>
            </tr></tbody>
          </table></div>
        </template>
        <small>{{ model.metadata_source }}</small><pre v-if="!selected">{{ JSON.stringify(model.training_config, null, 2) }}</pre>
      </details>
    </article>
    <p v-if="!filtered.length && !error && !loading">暂无符合条件的成功模型。<template v-if="selected && status === 'compatible'">可切换“有差异”查看和选择其他模型。</template></p>
    <nav v-if="filtered.length" class="workflow-pagination" aria-label="历史模型分页">
      <span role="status">共 {{ filtered.length }} 个 · 每页 5 个 · 第 {{ pagination.page }} / {{ pagination.pageCount }} 页</span>
      <div><button class="button secondary" type="button" :disabled="pagination.page === 1" @click="currentPage = pagination.page - 1">上一页</button><button class="button secondary" type="button" :disabled="pagination.page === pagination.pageCount" @click="currentPage = pagination.page + 1">下一页</button></div>
    </nav>
    <p v-if="selected?.some(id => !entries.some(m => m.id === id))" class="error-message">存在不可用的历史模型，请刷新并重新选择。<button type="button" class="button secondary" @click="selected.splice(0)">清空选择</button></p>
  </section>
</template>
<style scoped>
.model-entry { padding: 14px; margin: 10px 0; border: 1px solid #e1e7f3; background: #f8faff; border-radius: 10px; }
.comparison-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }
.comparison-tabs button { padding: 8px 14px; border: 1px solid #e0e7f4; border-radius: 9px; background: #f5f7fc; color: #526583; cursor: pointer; }
.comparison-tabs button.active { background: #eaf0ff; border-color: #8daafa; color: #305ecb; }
.comparison-tabs span { margin-left: 5px; font-variant-numeric: tabular-nums; }
.comparison-reasons, li { font-size: 12px; line-height: 1.7; color: #79633b; overflow-wrap: anywhere; }
.tone-danger { color: #b84451; background: #feebef; }
.parameter-legend { display: flex; flex-wrap: wrap; gap: 16px; font-size: 12px; }
.parameter-same { color: #18754a; }
.parameter-different { color: #b43746; }
.parameter-table { overflow-x: auto; margin: 12px 0; border: 1px solid #dfe6ee; border-radius: 8px; }
.parameter-table table { width: 100%; border-collapse: collapse; table-layout: fixed; min-width: 440px; font-size: 12px; }
.parameter-table th, .parameter-table td { padding: 10px; text-align: left; overflow-wrap: anywhere; border-bottom: 1px solid #e5eaf0; }
.parameter-table thead { background: #edf2f8; color: #526583; }
.parameter-table tr.parameter-same { background: #f2faf5; }
.parameter-table tr.parameter-different { background: #fff5f5; }
.parameter-table th:last-child { width: 50px; }
.model-title { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.model-title input[type="checkbox"] { width: 16px; height: 16px; padding: 0; flex-shrink: 0; accent-color: #5277df; }
.selected-models { margin: 14px 0; color: #526583; font-size: 12px; }
.model-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.model-chips button { border: 1px solid #d4dff8; background: #edf3ff; color: #365fc3; border-radius: 8px; padding: 5px 10px; max-width: 100%; overflow-wrap: anywhere; }
small { display: block; margin: 8px 0; color: #71809a; }
summary { cursor: pointer; color: #486ce0; margin-top: 12px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
</style>
