<script setup>
import { computed } from 'vue'
import { modelDetailRows, domainTokenShares } from '../analysis-model-details'
const props = defineProps({ model: { type: Object, required: true } })
const rows = computed(() => modelDetailRows(props.model))
const metrics = computed(() => rows.value.slice(-3))
const parameters = computed(() => rows.value.slice(1, -3))
const shares = computed(() => domainTokenShares(props.model).sort((a, b) => b.value - a.value))
const percentage = value => `${(value * 100).toFixed(2)}%`
</script>

<template>
  <div class="experiment-summary">
    <div class="strategy-banner"><span>配比策略</span><strong>{{ rows[0].value }}</strong><span class="record-tag">实际报告与提交配置</span></div>
    <dl class="sample-metrics"><div v-for="(row, index) in metrics" :key="row.label" :class="{ 'sample-highlight': index === 1 }"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl>
    <div class="experiment-layout">
      <section class="domain-mix" aria-label="实际领域 Token 占比">
        <div class="block-heading"><h4>实际领域占比</h4><span>按采样 Token 统计</span></div>
        <ul v-if="shares.length" class="domain-shares">
          <li v-for="item in shares" :key="item.name" :aria-label="`${item.name} ${percentage(item.value)}`">
            <div class="share-heading"><strong>{{ item.name }}</strong><b>{{ percentage(item.value) }}</b></div>
            <div class="share-track" aria-hidden="true"><span :style="{ width: percentage(item.value) }"></span></div>
          </li>
        </ul>
        <p v-else class="missing-value">报告未记录领域 Token 占比</p>
        <p class="summary-note">展示实际采样结果，不以配置比例代替，不代表训练累计消耗量。</p>
      </section>
      <section v-if="parameters.length" class="parameter-panel">
        <div class="block-heading"><h4>QuaDMix 实验配置</h4><span>提交时记录</span></div>
        <dl class="parameter-fields"><div v-for="row in parameters" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl>
      </section>
    </div>
    <details class="summary-source"><summary>统计口径与历史记录说明</summary>
      <p>{{ model.sampling?.token_method ? `Token 统计方式：${model.sampling.token_method}。` : '旧报告未记录 Token 统计方式。' }}重复入选的文本计入采样量，缺失字段不会按默认值补填。</p>
      <p v-if="model.experiment_config?.type === 'quadmix'">ω、ε、λ、η 展示提交时的搜索范围，不是搜索后最终选定的参数；历史非零下限按原报告展示。</p>
    </details>
  </div>
</template>

<style scoped>
.experiment-summary { margin-top: 18px; color: #243b59; }
.strategy-banner { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.strategy-banner > span { font-size: 12px; color: #6b7d94; } .strategy-banner strong { padding: 7px 12px; border-radius: 8px; background: #eaf0fd; color: #375ca9; font-size: 14px; }
.strategy-banner .record-tag { margin-left: auto; }
.sample-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 0 0 20px; }
.sample-metrics > div { padding: 18px; border: 1px solid #e0e8f2; border-radius: 12px; background: #f7faff; min-width: 0; }
.sample-metrics .sample-highlight { border-color: #d2def5; background: #edf3ff; }
dt { font-size: 12px; color: #60758e; line-height: 1.7; } dd { margin: 8px 0 0; font-size: 17px; font-weight: 700; line-height: 1.7; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.sample-highlight dd { color: #365fae; }
.experiment-layout { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 22px; }
.domain-mix, .parameter-panel { min-width: 0; padding: 20px; border: 1px solid #e2e9f2; border-radius: 14px; background: white; }
.block-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 20px; }
.block-heading h4 { margin: 0; font-size: 15px; color: #273e5e; } .block-heading > span { font-size: 11px; color: #7b8da5; }
.domain-shares { padding: 0; margin: 0; list-style: none; display: grid; gap: 17px; }
.share-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; margin-bottom: 7px; font-size: 14px; }
.share-heading strong { overflow-wrap: anywhere; } .share-heading b { color: #315aab; font-size: 20px; font-variant-numeric: tabular-nums; }
.share-track { height: 9px; border-radius: 8px; background: #eaf0f9; overflow: hidden; } .share-track span { display: block; height: 100%; background: linear-gradient(90deg, #7298e7, #466fcb); border-radius: inherit; }
.parameter-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 0; } .parameter-fields dd { font-size: 15px; margin-top: 4px; } .parameter-fields > div { min-width: 0; padding-bottom: 10px; border-bottom: 1px solid #edf1f7; }
.summary-note, .missing-value, .summary-source { color: #6d8098; font-size: 12px; line-height: 1.8; } .summary-note { margin: 20px 0 0; }
.summary-source { margin-top: 16px; } .summary-source summary { cursor: pointer; } .summary-source p { margin: 8px 0 0; }
@media (max-width: 1000px) { .experiment-layout { grid-template-columns: 1fr; } }
@media (max-width: 680px) { .sample-metrics { grid-template-columns: 1fr; } .strategy-banner .record-tag { margin-left: 0; } }
</style>
