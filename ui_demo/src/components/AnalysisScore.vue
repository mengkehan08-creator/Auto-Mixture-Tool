<script setup>
import { formatScore } from '../result-scores'
defineProps({ value: { default: null }, metric: { type: String, default: 'accuracy' }, bestLabel: { type: String, default: '' } })
</script>

<template>
  <span class="analysis-score" :class="{ 'score-best': bestLabel && Number.isFinite(value) }">
    <span class="score-value">{{ formatScore(value, metric) }}</span>
    <span v-if="bestLabel && Number.isFinite(value)" class="score-badge">{{ bestLabel }}</span>
  </span>
</template>

<style scoped>
.analysis-score { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px; font-variant-numeric: tabular-nums; }
.score-value { white-space: nowrap; }
.score-best { color: #bb2737; font-weight: 700; }
.score-badge { border-radius: 5px; padding: 1px 6px; background: #fff0f1; color: #bb2737; font-size: 11px; white-space: nowrap; font-weight: 600; }
</style>
