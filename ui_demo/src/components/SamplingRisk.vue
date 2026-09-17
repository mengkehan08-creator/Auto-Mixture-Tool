<script setup>
import { computed } from 'vue'
import { defaultSamplingBounds, sampleScenario, samplingRisk, formatTokens } from '../budget-estimates'
import { strategyLabel } from '../strategy-names'
const props = defineProps({ strategy: Object, budget: Number, datasetTokens: Number })
const scenario = computed(() => sampleScenario(props.datasetTokens, props.strategy.samplingBounds || defaultSamplingBounds()))
const risk = computed(() => samplingRisk(props.budget, scenario.value))
</script>
<template>
  <section class="sampling-risk" :class="{ warning: risk.warning }" :role="risk.warning ? 'alert' : 'status'">
    <div class="risk-heading"><strong>数据重复使用预判</strong><span class="risk-state">{{ risk.warning ? '请注意：存在重复使用风险' : '请留意两种重复来源' }}</span></div>
    <p class="strategy-label">{{ strategyLabel(strategy) }}</p>
    <div class="sampling-note">
      <strong>① 采样时：QuaDMix 本身就可能让同一篇文本入选两次</strong>
      <p>即使训练只读取一轮，部分文本也可能被使用两次。并非所有文本都固定采样两倍，实际次数取决于参数与随机抽样；两次也不是严格上限。</p>
    </div>
    <div class="training-note">
      <strong>② 训练时：预算超过采样量，还会循环读取采样集</strong>
      <p v-if="scenario">预计采样量（包含重复入选）：<b>{{ formatTokens(scenario.midpoint) }} Token</b>。范围端点情景：{{ formatTokens(scenario.low) }} ～ {{ formatTokens(scenario.high) }} Token。</p>
      <p v-if="risk.ratio !== null">训练预算 {{ formatTokens(budget) }} Token，约相当于 <b class="repeat-ratio">{{ risk.ratio > 3 && risk.ratio.toFixed(2) === '3.00' ? '略高于 3' : risk.ratio.toFixed(2) }} 倍</b>采样集 Token 总量。</p>
      <p v-else-if="risk.warning" class="risk-action">当前参数范围预计无可用采样数据，请调整采样参数。</p>
      <p v-else-if="scenario">填写有效的训练 Token 预算后自动判断循环读取风险。</p>
      <p v-else>请先校验输入数据。系统根据数据总量及 ω、ε、λ、η 范围预估，修改参数或训练预算后实时更新。</p>
      <p v-if="risk.ratio !== null && risk.warning" class="risk-action">告警：训练预算已超过预计采样量的 3 倍。采样内重复还会叠加训练循环，部分文本可能被使用更多次。建议降低训练预算或增加有效且不重复的采样数据；仍可继续提交。</p>
      <p v-else-if="risk.ratio !== null" class="risk-action">未触发“超过 3 倍”告警，但采样内仍可能有重复，不代表每篇文本只训练一次。</p>
    </div>
    <p class="risk-example">举例：某篇文本被采样 2 次，若整个采样集再完整读取 3 轮，该文本会累计使用 6 次。这是说明示例，不是本次实测次数。</p>
    <p class="risk-footnote">预计采样量已计入采样函数中的重复入选，不能再统一乘以 2。倍数按参数范围中点情景估算，并非每个 Token 的实际使用次数；最终以采样、裁剪和训练记录为准。超过 3 倍提示风险，不阻止提交。</p>
  </section>
</template>
<style scoped>
.sampling-risk { margin-top: 18px; padding: 22px; border: 1px solid #d5dfed; border-left: 5px solid #5372be; border-radius: 12px; background: #f6f8fc; color: #283c59; font-size: 15px; overflow-wrap: anywhere; }
.risk-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.risk-heading > strong { font-size: 19px; }
.risk-state { font-size: 14px; font-weight: 600; }
.strategy-label { color: #465a76; }
.sampling-note { padding: 14px 16px; border-radius: 8px; background: #fff3dd; color: #68400d; }
.training-note { margin-top: 18px; }
.sampling-note > strong, .training-note > strong { font-size: 16px; line-height: 1.7; }
.repeat-ratio { font-size: 24px; white-space: nowrap; }
.risk-action { font-weight: 650; }
.risk-example { border-top: 1px solid #d5dfed; padding-top: 12px; }
.risk-footnote { font-size: 14px; color: #465a76; }
.sampling-risk.warning { border-color: #d64a59; background: #fff4f4; }
.warning .risk-heading, .warning .repeat-ratio, .warning .risk-action { color: #ac172d; }
p { margin: 8px 0; line-height: 1.8; }
@media (max-width: 600px) { .sampling-risk { padding: 16px; } }
</style>
