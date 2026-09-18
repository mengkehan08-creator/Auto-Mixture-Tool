<script setup>
import { modelDetailRows, domainTokenSummary } from '../analysis-model-details'
defineProps({ model: { type: Object, required: true } })
</script>

<template>
  <div class="experiment-summary">
    <dl class="experiment-fields"><div v-for="row in modelDetailRows(model)" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl>
    <div class="domain-mix"><strong>实际领域占比（Token 占比）</strong><p>{{ domainTokenSummary(model) }}</p></div>
    <p class="summary-note">采样量与领域占比来自该模型的采样报告，不使用配置比例替代；不代表训练累计消耗量。{{ model.sampling?.token_method ? `Token 统计方式：${model.sampling.token_method}。` : '旧报告未记录 Token 统计方式。' }}</p>
    <p v-if="model.experiment_config?.type === 'quadmix'" class="summary-note">ω、ε、λ、η 展示提交时的搜索范围，不是搜索后最终选定的参数；缺失字段不按当前默认值补填。</p>
  </div>
</template>

<style scoped>
.experiment-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 14px 0; }
.experiment-fields > div { min-width: 0; padding: 14px; border: 1px solid #eee1e5; border-radius: 10px; background: #ffffffc9; }
dt { color: #68788f; font-size: 12px; line-height: 1.6; } dd { margin: 6px 0 0; color: #203354; font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
.domain-mix { padding: 14px; border-radius: 10px; background: #f3f6fc; color: #203354; font-size: 14px; }
.domain-mix p { margin: 8px 0 0; line-height: 1.8; overflow-wrap: anywhere; }
.summary-note { color: #68788f; font-size: 12px; line-height: 1.7; margin: 10px 0; }
</style>
