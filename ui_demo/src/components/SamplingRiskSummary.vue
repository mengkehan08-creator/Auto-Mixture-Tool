<script setup>
import { computed, ref } from 'vue'
import { defaultSamplingBounds, sampleScenario, samplingRisk } from '../budget-estimates.js'
import { strategyLabel } from '../strategy-names.js'
import SamplingRisk from './SamplingRisk.vue'

const props = defineProps({ strategies: Array, budget: Number, datasetTokens: Number })
const expanded = ref(false)
const selectedId = ref(null)
const rows = computed(() => props.strategies.filter(s => s.type === 'quadmix').map(strategy => ({ strategy,
  ...samplingRisk(props.budget, sampleScenario(props.datasetTokens, strategy.samplingBounds || defaultSamplingBounds())) })))
const warnings = computed(() => rows.value.filter(r => r.warning).length)
const unknown = computed(() => rows.value.filter(r => r.ratio === null && !r.warning).length)
const highest = computed(() => Math.max(0, ...rows.value.map(r => r.ratio ?? 0)))
const selected = computed(() => rows.value.find(r => String(r.strategy.id) === String(selectedId.value)) || rows.value[0])
</script>

<template>
  <section v-if="rows.length" class="risk-summary" :class="{ warning: warnings }">
    <div :role="warnings ? 'alert' : 'status'"><h4>数据重复使用预判 <span v-if="warnings">{{ warnings }} 项告警</span></h4>
      <p v-if="warnings">{{ warnings }} 项策略预计重复使用超过 3 倍或无可用采样数据<span v-if="highest">，最高约 <b>{{ highest > 3 && highest.toFixed(2) === '3.00' ? '略高于 3' : highest.toFixed(2) }} 倍</b></span>。仅提醒，不阻止提交。</p>
      <p v-else-if="unknown">{{ unknown }} 项策略暂无法预估，请先完成数据校验并填写有效预算。</p>
      <p v-else>未触发超过 3 倍告警，最高约 <b>{{ highest.toFixed(2) }} 倍</b>；QuaDMix 采样内仍可能重复。</p>
    </div>
    <details @toggle="expanded = $event.target.open"><summary>{{ expanded ? '收起详细说明' : '查看详细说明与各策略预判' }}</summary>
      <div v-if="expanded" class="risk-details">
        <label class="field"><span>查看策略</span><select :value="selected?.strategy.id" @change="selectedId = $event.target.value"><option v-for="row in rows" :key="row.strategy.id" :value="row.strategy.id">{{ strategyLabel(row.strategy) }}{{ row.warning ? ' · 告警' : '' }}</option></select></label>
        <SamplingRisk v-if="selected" :strategy="selected.strategy" :budget="budget" :dataset-tokens="datasetTokens" />
      </div>
    </details>
  </section>
</template>

<style scoped>
.risk-summary { margin-top: 20px; padding: 16px 18px; border: 1px solid #dce5f4; border-left: 4px solid #6887ca; border-radius: 12px; background: #f6f9fe; color: #456080; }
h4 { display: flex; align-items: center; gap: 12px; margin: 0; font-size: 14px; } h4 span { padding: 2px 8px; border-radius: 6px; background: #ffe4e8; font-size: 12px; }
p { margin: 6px 0 0; font-size: 13px; line-height: 1.8; } .warning { border-color: #efb9c2; border-left-color: #ce4053; background: #fff5f5; color: #a4293c; }
summary { width: fit-content; margin-top: 10px; color: #4269bc; cursor: pointer; font-size: 13px; font-weight: 600; } summary:focus-visible { outline: 2px solid #5379dc; outline-offset: 3px; }
.risk-details { margin-top: 16px; padding-top: 16px; border-top: 1px solid #dfe6f1; color: #456080; } .risk-details .field { max-width: 640px; }
</style>
