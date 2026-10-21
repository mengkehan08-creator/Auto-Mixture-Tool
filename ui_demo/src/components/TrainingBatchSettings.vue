<script setup>
import { computed, ref, useId, watch } from 'vue'
import { apiRequest } from '../api.js'

const props = defineProps({
  mode: { type: String, default: 'auto' }, batchSize: { type: [Number, String], default: null },
  modelObsUri: String, baseModelTag: String, nodes: { type: Array, required: true },
  tokenBudget: { type: [Number, String], default: null }, deviceBatchSize: { type: Number, default: 1 },
  numIterations: { type: Number, default: 0 },
})
const emit = defineEmits(['update:mode', 'update:batchSize', 'ready'])
const modeName = useId()
const pending = ref(true), error = ref(''), result = ref(null)
const format = value => value == null ? '—' : Number(value).toLocaleString('zh-CN')
const request = computed(() => ({
  model_obs_uri: props.modelObsUri, nodes: props.nodes,
  training: {
    base_model_tag: props.baseModelTag, devices_per_node: 8, device_batch_size: props.deviceBatchSize,
    batch_size_mode: props.mode, num_iterations: props.numIterations,
    ...(props.tokenBudget != null ? { token_budget: props.tokenBudget } : {}),
    ...(props.mode === 'fixed' ? { total_batch_size: props.batchSize } : {}),
  },
}))
watch(() => JSON.stringify(request.value), (serialized, _, onCleanup) => {
  const value = JSON.parse(serialized)
  pending.value = true; error.value = ''; result.value = null; emit('ready', false)
  if (typeof window === 'undefined') return
  let active = true
  const timer = setTimeout(async () => {
    try {
      if (!value.model_obs_uri || !value.training.base_model_tag) throw new Error('请填写模型 OBS 目录和基础模型标签，读取后计算训练计划。')
      const response = await apiRequest('training-plan', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
      })
      if (!active) return
      result.value = response; error.value = (response.errors || []).join('；')
      emit('ready', response.ready === true)
    } catch (reason) { if (active) error.value = reason.message }
    finally { if (active) pending.value = false }
  }, 250)
  onCleanup(() => { active = false; clearTimeout(timer) })
}, { immediate: true })

function selectMode(mode) {
  if (mode === 'fixed' && !props.batchSize && result.value?.recommended_batch_size) emit('update:batchSize', result.value.recommended_batch_size)
  emit('update:mode', mode)
}
</script>

<template>
  <section class="batch-settings" aria-label="全局 batch 与训练计划">
    <fieldset class="batch-mode">
      <legend>全局 batch Token 数</legend>
      <div class="batch-options">
        <label><input type="radio" :name="modeName" value="auto" :checked="mode === 'auto'" @change="selectMode('auto')" />自动推荐</label>
        <label><input type="radio" :name="modeName" value="fixed" :checked="mode === 'fixed'" @change="selectMode('fixed')" />手动固定</label>
      </div>
      <p v-if="mode === 'auto'">根据基础模型与本次节点配置，向上选择各策略都能整除的共同 batch。</p>
      <label v-else class="field batch-input"><span>固定全局 batch Token 数</span><input type="number" min="1" step="1" :value="batchSize" :aria-invalid="Boolean(error)" @input="emit('update:batchSize', $event.target.value === '' ? '' : Number($event.target.value))" /><small>全部节点每个优化步合计的 Token 数；不兼容时会阻止提交。</small></label>
    </fieldset>
    <p v-if="pending" role="status" class="batch-status">正在读取基础模型元数据并计算训练计划…</p>
    <template v-else>
      <p v-if="error" role="alert" class="batch-error">{{ error }}</p>
      <button v-if="mode === 'fixed' && result?.recommended_batch_size && (error || batchSize !== result.recommended_batch_size)" type="button" class="button secondary batch-use" @click="emit('update:batchSize', result.recommended_batch_size)">使用推荐值 {{ format(result.recommended_batch_size) }}</button>
      <div v-if="result" class="batch-plan">
        <div class="batch-heading"><span>{{ result.ready ? '本次全局 batch' : '推荐全局 batch' }}</span><strong>{{ format(result.ready ? result.plans[0]?.total_batch_size : result.recommended_batch_size) }} <small>Tokens / 步</small></strong></div>
        <p>基础模型 batch {{ format(result.plans[0]?.checkpoint_batch_size) }} · 序列长度 {{ format(result.plans[0]?.sequence_len) }} · 单卡 batch {{ deviceBatchSize }}</p>
        <div class="batch-table-wrap"><table><thead><tr><th scope="col">训练规模</th><th scope="col">梯度累积</th><th scope="col">预计步数</th><th scope="col">实际训练 Tokens</th></tr></thead><tbody>
          <tr v-for="plan in result.plans" :key="plan.nodes"><td>{{ plan.nodes }} 节点 · {{ plan.nodes * 8 }} 卡</td><td>{{ plan.grad_accum_steps == null ? '—' : `${format(plan.grad_accum_steps)} 次` }}</td><td>{{ format(plan.num_iterations) }}</td><td>{{ format(plan.actual_tokens) }}</td></tr>
        </tbody></table></div>
        <p v-if="result.plans.some(plan => plan.rounding_tokens > 0)">预算按完整优化步向上取整；实际训练量最多比预算多出不到一个全局 batch。</p>
        <p v-if="result.plans.some(plan => plan.num_iterations == null) && result.ready">填写训练 Token 预算后可显示预计步数；历史作业也可沿用采样统计预算。</p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.batch-settings { margin: 20px 0; padding: 20px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.batch-mode { min-width: 0; margin: 0; padding: 0; border: 0; }
.batch-mode legend { margin-bottom: 12px; padding: 0; font-size: 14px; font-weight: 600; color: #2b4063; }
.batch-options { display: flex; flex-wrap: wrap; gap: 12px 24px; }
.batch-options label { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; white-space: nowrap; cursor: pointer; }
.batch-options input { width: 16px; height: 16px; flex-shrink: 0; margin: 0; padding: 0; accent-color: var(--accent); }
.batch-options input:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.batch-settings p { margin: 10px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.8; }
.batch-input { max-width: 440px; margin-top: 16px; }
.batch-plan { margin-top: 18px; }
.batch-heading { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 16px; }
.batch-heading span { color: #3e506a; font-size: 13px; }
.batch-heading strong { font-size: 23px; color: #284b9b; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.batch-heading small { font-size: 12px; color: var(--text-secondary); font-weight: 400; }
.batch-table-wrap { max-width: 100%; overflow-x: auto; margin-top: 12px; }
.batch-plan table { width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.batch-plan th, .batch-plan td { padding: 10px 14px 10px 0; text-align: left; border-bottom: 1px solid #edf1f7; }
.batch-plan th { color: var(--text-secondary); font-weight: 500; }
.batch-plan td { color: #253c61; }
.batch-settings .batch-error { padding: 12px 14px; border: 1px solid #efcbd1; border-radius: 8px; color: #9d2438; background: #fff5f6; }
.batch-use { margin-top: 12px; }
@media (max-width: 640px) { .batch-settings { padding: 16px 0; } .batch-heading strong { font-size: 21px; } }
</style>
