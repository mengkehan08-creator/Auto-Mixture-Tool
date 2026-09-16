<script setup>
import { ref, computed, watch } from 'vue'
import { apiRequest } from '../api'
import { ArrowLeft, RefreshCw, ChartColumn } from '@lucide/vue'
import AnalysisScore from './AnalysisScore.vue'
import ScoreComparisonChart from './ScoreComparisonChart.vue'
import { scoreRanking, formatScore } from '../result-scores'

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
const percent = value => formatScore(value)
const rankings = computed(() => {
  const models = report.value?.models || []
  const sections = Object.fromEntries(['metrics', 'aggregates'].map(section => {
    const tasks = [...new Set(models.flatMap(model => Object.keys(model[section])))]
    return [section, Object.fromEntries(tasks.map(name => [name, Object.fromEntries(
      ['accuracy', 'centered'].map(metric => [metric, scoreRanking(models, model => model[section][name]?.[metric])]),
    )]))]
  }))
  return { mean: scoreRanking(models, model => model.mean_accuracy), ...sections }
})
function bestLabel(model, name = null, metric = 'accuracy', section = 'metrics') {
  const ranking = name === null ? rankings.value.mean : rankings.value[section]?.[name]?.[metric]
  return ranking?.ids.includes(model.id) ? ranking.label : ''
}
const conclusionParts = computed(() => report.value?.conclusion_parts || report.value?.conclusions.map(text => [{ text }]) || [])
const winners = computed(() => report.value?.models.filter(model => rankings.value.mean.ids.includes(model.id)) || [])
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
      <button type="button" class="button secondary" @click="emit('back')"><ArrowLeft :size="16" aria-hidden="true" />返回作业详情</button>
      <button type="button" class="button secondary" :disabled="loading" @click="load"><RefreshCw :size="16" aria-hidden="true" />{{ loading ? '正在读取…' : '刷新结果' }}</button>
    </div>
    <header class="analysis-heading"><span class="analysis-eyebrow"><ChartColumn :size="18" aria-hidden="true" />实验结果分析</span><h2>{{ data?.name || '评测结果' }}</h2><p>对比策略表现，查看真实得分与分析依据。</p></header>
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
      <article v-if="winners.length" class="analysis-panel winner-panel"><h3>平均正确率最高的模型与实验配置</h3>
        <section v-for="model in winners" :key="model.id"><h4>{{ model.name }} <AnalysisScore :value="model.mean_accuracy" :best-label="bestLabel(model)" /></h4>
          <p>共同评测项 {{ report.common_tasks.length }} 项 · 模型标签 {{ model.model_tag || '未记录' }} · checkpoint {{ model.step ?? '未记录' }}</p>
          <div class="winner-config"><div v-for="(value, key) in model.experiment_config || {}" :key="key"><span>{{ key }}</span><strong>{{ typeof value === 'object' ? JSON.stringify(value) : value }}</strong></div><div v-for="(value, key) in model.training" :key="key"><span>{{ key }}</span><strong>{{ value }}</strong></div></div>
          <p v-if="!Object.keys(model.experiment_config || {}).length">旧报告未记录完整配比配置；这里只展示已知信息，不推测缺失参数。</p>
        </section>
      </article>
      <div class="analysis-reading-guide"><strong>{{ report.name }}</strong><span><i aria-hidden="true"></i>红色表示该指标最高分，包含并列</span><span>正确率用 % · 校正分用小数</span></div>
      <div class="analysis-metrics"><div><strong>{{ report.models.length }}</strong><span>参评模型</span></div><div><strong>{{ report.tasks.length }}</strong><span>已记录评测项</span></div><div><strong>{{ report.common_tasks.length }}</strong><span>共同有效评测项</span></div></div>
      <div class="analysis-charts">
        <article class="analysis-panel">
          <h3>平均正确率</h3><p>基于 {{ report.common_tasks.length }} 个共同评测项等权计算，越高越好。</p>
          <ScoreComparisonChart :models="report.models" />
          <p v-if="!report.common_tasks.length">无共同有效评测项，不进行均值排序。</p>
        </article>
        <article class="analysis-panel">
          <h3>单项表现对比</h3>
          <label class="field"><span>评测项</span><select v-model="selectedTask"><option v-for="name in report.tasks" :key="name" :value="name">{{ name }}</option></select></label>
          <ScoreComparisonChart :models="report.models" :task="selectedTask" />
        </article>
      </div>
      <article class="analysis-panel analysis-conclusions"><h3>结果解读</h3><ol><li v-for="(parts, index) in conclusionParts" :key="index"><span v-for="(part, partIndex) in parts" :key="partIndex" :class="{ 'conclusion-best': part.best }">{{ part.text }}</span></li></ol></article>
      <article class="analysis-panel"><h3>逐项得分</h3><p>同一行内比较正确率；最高分标红，缺失值不参与排名。</p>
        <div class="analysis-table-scroll" role="region" aria-label="逐项正确率对比" tabindex="0"><table><thead><tr><th scope="col">评测项</th><th v-for="model in report.models" :key="model.id" scope="col">{{ model.name }}</th></tr></thead><tbody><tr v-for="name in report.tasks" :key="name"><th scope="row">{{ name }}</th><td v-for="model in report.models" :key="model.id" :class="{ 'cell-best': bestLabel(model, name) }"><AnalysisScore :value="model.metrics[name]?.accuracy" :best-label="bestLabel(model, name)" /></td></tr></tbody></table></div>
        <details><summary>校正分数与官方汇总指标</summary><p>Centered 是基线校正分数，使用四位小数，可能为负。每个评测项、每类指标分别标记最高值，不与正确率混排。</p>
          <div v-for="model in report.models" :key="model.id"><h4>{{ model.name }}</h4><div class="analysis-table-scroll"><table><thead><tr><th scope="col">评测项</th><th scope="col">正确率（%）</th><th scope="col">Centered（校正分）</th></tr></thead><tbody><template v-for="section in ['metrics', 'aggregates']" :key="section"><tr v-for="(value, name) in model[section]" :key="name"><th scope="row">{{ name }}</th><td><AnalysisScore :value="value.accuracy" :best-label="bestLabel(model, name, 'accuracy', section)" /></td><td><AnalysisScore :value="value.centered" metric="centered" :best-label="bestLabel(model, name, 'centered', section)" /></td></tr></template></tbody></table></div></div>
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
      <article class="analysis-panel analysis-limitations"><h3>分析口径与限制</h3><p>{{ report.method }}</p><p>最高分按原始数值判断（并列容差 10⁻⁹），不按四舍五入后的显示值判断。存在缺失值时，“最高”仅指已提供结果中的最高值。</p><ul><li v-for="(line, index) in report.warnings" :key="index">{{ line }}</li></ul><p class="analysis-source">数据来源：{{ report.source }}</p></article>
    </template>
  </section>
</template>

<style scoped>
.winner-panel { border-color: #edbcc5 !important; background: linear-gradient(120deg, #fff3f4, #fff) !important; }
.winner-panel h4 { display: flex; gap: 18px; align-items: center; flex-wrap: wrap; color: #b92339; margin: 10px 0; overflow-wrap: anywhere; }
.winner-config { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
.winner-config > div { display: grid; gap: 4px; padding: 12px; border-radius: 10px; background: #ffffffb3; overflow-wrap: anywhere; }
.winner-config span { font-size: 12px; color: #6a7890; } .winner-config strong { font-size: 13px; }
.result-analysis { display: grid; gap: 20px; min-width: 0; color: #203354; }
.analysis-toolbar, .analysis-tabs { display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; }
.analysis-tabs { justify-content: flex-start; }
.analysis-heading { padding: 24px; border-radius: 16px; background: linear-gradient(110deg, #edf2ff, #f9fbff); overflow-wrap: anywhere; }
.analysis-heading h2 { margin: 8px 0; font-size: 24px; }
.analysis-heading p, .analysis-panel > p { color: #5c6e88; line-height: 1.7; }
.analysis-eyebrow { display: flex; align-items: center; gap: 8px; color: #4d68cc; font-size: 13px; font-weight: 600; }
.analysis-reading-guide { display: flex; align-items: center; flex-wrap: wrap; gap: 12px 24px; color: #5c6e88; font-size: 13px; }
.analysis-reading-guide strong { color: #203354; }
.analysis-reading-guide i { display: inline-block; width: 8px; height: 8px; margin-right: 5px; border-radius: 50%; background: #bb2737; }
.analysis-metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.analysis-metrics > div { background: #eef3ff; border-radius: 12px; padding: 18px; display: grid; gap: 6px; }
.analysis-metrics strong { font-size: 28px; color: #435ebc; }
.analysis-metrics span { font-size: 13px; }
.analysis-charts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; align-items: stretch; }
.analysis-panel { padding: 24px; border: 1px solid #dce5f3; border-radius: 16px; background: #fff; min-width: 0; }
.analysis-panel h3 { margin: 0 0 14px; font-size: 17px; }
.analysis-panel p, .analysis-panel li { overflow-wrap: anywhere; font-size: 14px; line-height: 1.8; }
.analysis-axis { display: flex; justify-content: space-between; color: #63728c; font-size: 12px; margin: 20px 0 12px; }
.analysis-bar-row { margin: 14px 0; }
.analysis-bar-row > div:first-child { display: flex; align-items: baseline; flex-wrap: wrap; justify-content: space-between; gap: 6px 16px; font-size: 14px; margin-bottom: 8px; }
.analysis-bar-row span { overflow-wrap: anywhere; }
.analysis-bar-row strong { white-space: nowrap; font-variant-numeric: tabular-nums; }
.analysis-track { background: #edf1f8; height: 12px; border-radius: 6px; overflow: hidden; }
.analysis-track > span { display: block; height: 100%; background: #8098dd; }
.bar-best .analysis-track > span { background: #cc3445; }
.analysis-table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 13px; border-bottom: 1px solid #e5ebf4; text-align: left; min-width: 110px; overflow-wrap: anywhere; }
thead { background: #f4f7fc; }
tbody tr:hover { background: #f8faff; }
.cell-best { background: #fff7f7; }
td { font-variant-numeric: tabular-nums; }
details { margin-top: 16px; }
summary { cursor: pointer; font-weight: 600; line-height: 1.7; }
.analysis-notice { background: #fff8eb; padding: 18px; border-radius: 12px; color: #775719; overflow-wrap: anywhere; }
.analysis-conclusions { background: #f5f8ff; }
.analysis-conclusions ol { padding-left: 24px; margin-bottom: 0; }
.analysis-conclusions li { padding-left: 6px; margin: 12px 0; }
.analysis-conclusions li::marker { color: #5d75af; font-weight: 600; }
.conclusion-best { color: #bb2737; font-weight: 700; font-variant-numeric: tabular-nums; }
.analysis-limitations { background: #fafbfe; }
.analysis-source { color: #5c6e88; }
.analysis-models { display: grid; gap: 8px; }
@media (max-width: 900px) { .analysis-charts { grid-template-columns: 1fr; } }
@media (max-width: 540px) { .analysis-panel { padding: 16px; } .analysis-metrics { grid-template-columns: 1fr; } }
</style>
