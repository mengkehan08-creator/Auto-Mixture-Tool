<script setup>
import { ref, computed, watch } from 'vue'
import { apiRequest } from '../api'

const props = defineProps({ workflowId: { type: String, required: true } })
const emit = defineEmits(['back'])
const data = ref(null)
const loading = ref(false)
const error = ref('')
const reportId = ref('')
const task = ref('')
const report = computed(() => data.value?.reports.find(item => item.id === reportId.value) || data.value?.reports[0])
const selectedTask = computed({
  get: () => report.value?.tasks.includes(task.value) ? task.value : report.value?.tasks[0],
  set: value => { task.value = value },
})
const colors = ['#526fe5', '#18857a', '#b87115', '#a34f93', '#3979a3', '#8a654c']
const percent = value => value == null ? '未提供' : `${(value * 100).toFixed(2)}%`
const centered = value => value == null ? '未提供' : value.toFixed(4)
const sampleSummary = model => Object.entries(model.sampling?.domain_ratios || {})
  .map(([name, value]) => `${name} ${percent(value)}`).join(' · ') || '未记录'
let requestVersion = 0
async function load() {
  const version = ++requestVersion
  loading.value = true
  error.value = ''
  try {
    const result = await apiRequest(`workflows/${props.workflowId}/analysis`)
    if (version === requestVersion) data.value = result
  } catch (reason) {
    if (version === requestVersion) error.value = reason.message
  } finally {
    if (version === requestVersion) loading.value = false
  }
}
watch(() => props.workflowId, () => {
  data.value = null
  reportId.value = ''
  task.value = ''
  load()
}, { immediate: true })
</script>

<template>
  <section class="result-analysis" aria-label="实验结果分析">
    <div class="analysis-toolbar">
      <button type="button" class="button secondary" @click="emit('back')">返回作业详情</button>
      <button type="button" class="button secondary" :disabled="loading" @click="load">{{ loading ? '正在读取…' : '刷新结果' }}</button>
    </div>
    <header class="analysis-heading"><span class="analysis-eyebrow">实验结果分析</span><h2>{{ data?.name || '评测结果' }}</h2><p>基于实际评测报告，比较模型表现与采样策略。不同评测集分别分析。</p></header>
    <p v-if="error" role="alert" class="error-message">{{ error }}</p>
    <p v-if="loading" role="status">正在读取评测报告…</p>
    <p v-if="data?.message" class="analysis-notice" role="status">{{ data.message }}</p>
    <div v-for="item in data?.errors || []" :key="item.source" class="analysis-notice">
      <strong>{{ item.name }}</strong><p>{{ item.message }}</p><code>{{ item.source }}</code>
    </div>
    <div v-if="data?.reports.length > 1" class="analysis-tabs" role="group" aria-label="选择评测集">
      <button v-for="item in data.reports" :key="item.id" type="button" class="button" :class="report?.id === item.id ? 'primary' : 'secondary'" :aria-pressed="report?.id === item.id" @click="reportId = item.id; task = ''">{{ item.name }}</button>
    </div>
    <template v-if="report">
      <div class="analysis-metrics"><div><strong>{{ report.models.length }}</strong><span>参评模型</span></div><div><strong>{{ report.tasks.length }}</strong><span>已记录评测项</span></div><div><strong>{{ report.common_tasks.length }}</strong><span>共同有效评测项</span></div></div>
      <div class="analysis-charts">
        <article class="analysis-panel">
          <h3>共同评测项 · 平均正确率</h3><p>各评测项等权平均，越高越好。不是官方综合指标。</p>
          <div class="analysis-axis"><span>0%</span><span>50%</span><span>100%</span></div>
          <div v-for="(model, index) in report.models" :key="model.id" class="analysis-bar-row">
            <div><span>{{ model.name }}</span><strong>{{ percent(model.mean_accuracy) }}</strong></div>
            <div class="analysis-track" role="img" :aria-label="`${model.name} 平均正确率 ${percent(model.mean_accuracy)}`"><span :style="{ width: `${(model.mean_accuracy ?? 0) * 100}%`, background: colors[index % colors.length] }"></span></div>
          </div>
          <p v-if="!report.common_tasks.length">无共同有效评测项，不进行均值排序。</p>
        </article>
        <article class="analysis-panel">
          <h3>单项表现对比</h3>
          <label class="field"><span>评测项</span><select v-model="selectedTask"><option v-for="name in report.tasks" :key="name" :value="name">{{ name }}</option></select></label>
          <div class="analysis-axis"><span>0%</span><span>50%</span><span>100%</span></div>
          <div v-for="(model, index) in report.models" :key="model.id" class="analysis-bar-row">
            <div><span>{{ model.name }}</span><strong>{{ percent(model.metrics[selectedTask]?.accuracy) }}</strong></div>
            <div class="analysis-track" role="img" :aria-label="`${model.name} ${selectedTask || ''} 正确率 ${percent(model.metrics[selectedTask]?.accuracy)}`"><span :style="{ width: `${(model.metrics[selectedTask]?.accuracy ?? 0) * 100}%`, background: colors[index % colors.length] }"></span></div>
          </div>
        </article>
      </div>
      <article class="analysis-panel analysis-conclusions"><h3>结果解读</h3><p v-for="(line, index) in report.conclusions" :key="index">{{ line }}</p></article>
      <article class="analysis-panel"><h3>逐项得分</h3><p>正确率以百分比展示；缺失指标保留为空，不补零。</p>
        <div class="analysis-table-scroll"><table><thead><tr><th scope="col">评测项</th><th v-for="model in report.models" :key="model.id" scope="col">{{ model.name }}</th></tr></thead><tbody><tr v-for="name in report.tasks" :key="name"><th scope="row">{{ name }}</th><td v-for="model in report.models" :key="model.id">{{ percent(model.metrics[name]?.accuracy) }}</td></tr></tbody></table></div>
        <details><summary>查看 Centered 与报告原始汇总指标</summary><p>Centered 是基线校正分数，可能为负数；与正确率含义不同，不混合排序。</p>
          <div v-for="model in report.models" :key="model.id"><h4>{{ model.name }}</h4><div class="analysis-table-scroll"><table><thead><tr><th>评测项</th><th>正确率</th><th>Centered</th></tr></thead><tbody><tr v-for="(value, name) in { ...model.metrics, ...model.aggregates }" :key="name"><th>{{ name }}</th><td>{{ percent(value.accuracy) }}</td><td>{{ centered(value.centered) }}</td></tr></tbody></table></div></div>
        </details>
      </article>
      <article class="analysis-panel"><h3>模型与采样记录</h3><div class="analysis-models">
        <details v-for="model in report.models" :key="model.id"><summary>{{ model.name }} · checkpoint {{ model.step ?? '未记录' }}</summary>
          <p>模型标签：{{ model.model_tag || '未记录' }}</p><p>来源实验：{{ model.source_workflow_id || '当前实验 / 旧版未记录' }}</p>
          <p>采样 Token 数：{{ model.sampling.tokens?.toLocaleString() ?? '未记录' }} · 训练文档数：{{ model.sampling.train_docs?.toLocaleString() ?? '未记录' }}</p>
          <p>实际领域配比（Token 占比）：{{ sampleSummary(model) }}</p>
          <p>配置领域比例：{{ Object.entries(model.configured_ratios || {}).map(([name, value]) => `${name}=${value}`).join(' · ') || '未记录 / 算法决定' }}</p>
          <p v-for="(value, key) in model.training" :key="key">{{ key }}：{{ value }}</p>
        </details></div></article>
      <article class="analysis-panel analysis-limitations"><h3>分析口径与限制</h3><p>{{ report.method }}</p><ul><li v-for="(line, index) in report.warnings" :key="index">{{ line }}</li></ul><p class="analysis-source">数据来源：{{ report.source }}</p></article>
    </template>
  </section>
</template>

<style scoped>
.result-analysis { display: grid; gap: 20px; min-width: 0; color: #203354; }
.analysis-toolbar, .analysis-tabs { display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; }
.analysis-tabs { justify-content: flex-start; }
.analysis-heading { padding: 8px 0; overflow-wrap: anywhere; }
.analysis-heading h2 { margin: 8px 0; font-size: 24px; }
.analysis-heading p, .analysis-panel > p { color: #5c6e88; line-height: 1.7; }
.analysis-eyebrow { color: #4d68cc; font-size: 13px; font-weight: 600; }
.analysis-metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.analysis-metrics > div { background: #eef3ff; border-radius: 12px; padding: 18px; display: grid; gap: 6px; }
.analysis-metrics strong { font-size: 28px; color: #435ebc; }
.analysis-metrics span { font-size: 13px; }
.analysis-charts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; align-items: start; }
.analysis-panel { padding: 24px; border: 1px solid #dce5f3; border-radius: 16px; background: #fff; min-width: 0; }
.analysis-panel h3 { margin: 0 0 14px; font-size: 17px; }
.analysis-panel p, .analysis-panel li { overflow-wrap: anywhere; font-size: 14px; line-height: 1.8; }
.analysis-axis { display: flex; justify-content: space-between; color: #63728c; font-size: 12px; margin: 20px 0 12px; }
.analysis-bar-row { margin: 14px 0; }
.analysis-bar-row > div:first-child { display: flex; justify-content: space-between; gap: 16px; font-size: 13px; margin-bottom: 7px; }
.analysis-bar-row span { overflow-wrap: anywhere; }
.analysis-bar-row strong { white-space: nowrap; font-variant-numeric: tabular-nums; }
.analysis-track { background: #edf1f8; height: 12px; border-radius: 6px; overflow: hidden; }
.analysis-track > span { display: block; height: 100%; }
.analysis-table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 13px; border-bottom: 1px solid #e5ebf4; text-align: left; min-width: 110px; overflow-wrap: anywhere; }
thead { background: #f4f7fc; }
td { font-variant-numeric: tabular-nums; }
details { margin-top: 16px; }
summary { cursor: pointer; font-weight: 600; line-height: 1.7; }
.analysis-notice { background: #fff8eb; padding: 18px; border-radius: 12px; color: #775719; overflow-wrap: anywhere; }
.analysis-conclusions { background: #f5f8ff; }
.analysis-limitations { background: #fafbfe; }
.analysis-source { color: #5c6e88; }
.analysis-models { display: grid; gap: 8px; }
@media (max-width: 900px) { .analysis-charts { grid-template-columns: 1fr; } }
@media (max-width: 540px) { .analysis-panel { padding: 16px; } .analysis-metrics { grid-template-columns: 1fr; } }
</style>
