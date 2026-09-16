<script setup>
import { computed } from 'vue'
import { defaultSamplingBounds, sampleScenario, samplingRisk, formatTokens } from '../budget-estimates'
import { strategyLabel } from '../strategy-names'
const props = defineProps({ strategy: Object, budget: Number, datasetTokens: Number })
const scenario = computed(() => sampleScenario(props.datasetTokens, props.strategy.samplingBounds || defaultSamplingBounds()))
const risk = computed(() => samplingRisk(props.budget, scenario.value))
</script>
<template>
  <section class="sampling-risk" :class="{ warning: risk.warning }" role="status">
    <strong>{{ strategyLabel(strategy) }} · {{ risk.warning ? '重复使用风险告警' : '数据重复使用预判' }}</strong>
    <p v-if="scenario">自动预计采样量：<b>{{ formatTokens(scenario.midpoint) }} Token</b>；范围端点情景：{{ formatTokens(scenario.low) }} ～ {{ formatTokens(scenario.high) }} Token。</p>
    <p v-if="risk.ratio !== null">训练预算 {{ formatTokens(budget) }} Token，约相当于 <b>{{ risk.ratio > 3 && risk.ratio.toFixed(2) === '3.00' ? '略高于 3' : risk.ratio.toFixed(2) }} 倍</b>采样量。依据：{{ risk.basis }}。</p>
    <p v-else-if="risk.warning">当前参数范围预计无可用采样数据，请调整采样参数。</p>
    <p v-else-if="scenario">填写有效的训练 Token 预算后自动判断重复使用风险。</p>
    <p v-else>校验输入数据后，系统根据数据总量及 ω、ε、λ、η 搜索范围自动预估，无需提供实际采样统计。修改参数或训练预算后实时更新。</p>
    <small>超过 3 倍时警告，不阻止提交。采样集内部重复、训练裁剪可能使实际重复更高；低于 3 倍不代表没有重复。</small>
  </section>
</template>
<style scoped>
.sampling-risk { margin-top: 16px; padding: 18px; border: 1px solid #dce7f3; border-radius: 12px; background: #f4f8fd; color: #49607e; font-size: 13px; }
.sampling-risk.warning { border-color: #efbcc4; color: #ad263b; background: #fff3f4; }
p { margin: 8px 0; line-height: 1.8; } small { display: block; line-height: 1.8; }
</style>
