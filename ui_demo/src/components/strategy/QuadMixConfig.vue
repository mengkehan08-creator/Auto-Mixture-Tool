<script setup>
import { strategyNameHint } from '../../strategy-names'
import { computed, watchEffect } from 'vue'
import { defaultSamplingBounds, samplingFields, validBounds, sampleScenario, formatTokens, proxyTrainingTokens } from '../../budget-estimates'
const props = defineProps({ modelValue: { type: Object, required: true }, datasetTokens: Number })
watchEffect(() => { if (!props.modelValue.samplingBounds) props.modelValue.samplingBounds = defaultSamplingBounds() })
const scenario = computed(() => sampleScenario(props.datasetTokens, props.modelValue.samplingBounds))
</script>

<template>
  <div class="form-grid three-cols">
    <label class="field"><span>策略名称（可自定义）</span><input v-model="modelValue.name" :placeholder="strategyNameHint(modelValue)" /></label>
    <label class="field"><span>代理实验数</span><input v-model.number="modelValue.proxyExperiments" type="number" min="1" /><small :class="{ 'few-experiments': modelValue.proxyExperiments < 50 }">建议不少于 50 个。过少可能导致回归无法区分配比、结果不稳定或重复；50 不是效果保证，还需检查验证表现。</small></label>
    <label class="field"><span>代理实验步数</span><input v-model.number="modelValue.proxySteps" type="number" min="1" /><small>每组实验预计训练消耗 <b>{{ formatTokens(proxyTrainingTokens(modelValue.proxySteps)) }}</b> Token。按默认 8 × 2048 Token/步计，含重复读取，不是最终子集量。自定义命令改变批量或序列长度后需重新核算。</small></label>
    <label class="field"><span>参数搜索次数</span><input v-model.number="modelValue.searchCount" type="number" min="1" /></label>
    <label class="field"><span>随机种子</span><input v-model.number="modelValue.seed" type="number" /></label>
    <label class="field"><span>设备类型</span><select v-model="modelValue.deviceType"><option>NPU</option></select><small>当前 ModelArts 启动模板适配 Ascend NPU。</small></label>
    <label class="field"><span>每节点设备数</span><input v-model.number="modelValue.devicesPerNode" type="number" min="1" /></label>
  </div>
  <div class="sampling-bounds"><h3>采样参数搜索范围</h3><p>填写实际参数值；上下限相同可固定该参数。各领域在这些范围内独立搜索。</p>
    <div class="form-grid two-cols"><section v-for="field in samplingFields" :key="field.key" class="bound-card"><h4>{{ field.label }}</h4><div class="form-grid two-cols">
      <label v-for="(label, index) in ['下限', '上限']" :key="label" class="field"><span>{{ label }}</span><input v-model.number="modelValue.samplingBounds[field.key][index]" :aria-label="`${field.key} ${label}`" type="number" min="0" :max="field.max" :step="field.step" /></label>
    </div><small>{{ field.help }}</small></section></div>
    <p v-if="!validBounds(modelValue.samplingBounds)" class="error-message">范围无效：上下限须为有限非负数，下限不能大于上限；ω、ε、η 上限不能超过 1。提交时会再次校验。</p>
  </div>
  <aside class="sampling-reference"><div><span>最终采样 Token</span><strong>实际值待统计</strong></div><p>以本次最终输出文本经训练 Tokenizer 统计的 Token 总数为准，重复入选的文本也计入。</p></aside>
  <div class="sampling-estimate" role="status"><template v-if="scenario"><strong>预计最终采样 Token 数：约 {{ formatTokens(scenario.midpoint) }}</strong><p>按参数范围中点计算；范围端点情景：{{ formatTokens(scenario.low) }} ～ {{ formatTokens(scenario.high) }} Token。修改 ω、ε、λ、η 后自动更新，与训练预算无关。</p></template><p v-else>输入数据自动校验通过、参数范围有效后，显示预计最终采样 Token 数。</p><small>按输入 Token 抽样估算量与采样函数计算，假设领域内 Token 排名连续。不是回归搜索预测、置信区间或数量保证；未扣除后续过滤与裁剪，重复文档计入。改变质量权重或范围后，搜索结果也可能改变。</small></div>
</template>
<style scoped>
.sampling-reference { display: flex; align-items: center; gap: 24px; padding: 16px 18px; margin-top: 22px; border: 1px solid #dce7f3; border-radius: 12px; background: #f2f7fc; }
.sampling-reference > div { flex: 0 0 auto; display: grid; gap: 3px; }
.sampling-reference span { color: #647792; font-size: 12px; }
.sampling-reference strong { color: #314e75; font-size: 14px; }
.sampling-reference p { margin: 0; padding-left: 22px; border-left: 1px solid #d7e2ef; font-size: 12px; line-height: 1.8; color: #5a6d87; }
.sampling-bounds { margin-top: 24px; padding-top: 22px; border-top: 1px solid #e0e8f3; } .sampling-bounds > p { font-size: 13px; color: #5d7089; }
.bound-card { padding: 16px; background: #f7f9fd; border: 1px solid #e0e8f3; border-radius: 12px; } .bound-card h4 { margin: 0 0 12px; font-size: 14px; color: #334f76; } .bound-card small { display: block; margin-top: 12px; color: #5d7089; line-height: 1.8; }
.sampling-estimate { margin-top: 14px; padding: 18px; border: 1px solid #d8e5f8; border-radius: 12px; color: #496584; background: #f5f9ff; font-size: 13px; } .sampling-estimate small { line-height: 1.8; } .field small.few-experiments { color: #956216; }
@media (max-width: 640px) { .sampling-reference { align-items: flex-start; flex-direction: column; gap: 10px; } .sampling-reference p { padding: 0; border: 0; } }
</style>
