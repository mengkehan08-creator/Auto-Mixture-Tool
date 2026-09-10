<script setup>
import { onMounted, reactive, ref } from 'vue'
import { apiRequest } from '../api'
import { validateJobCommands } from '../job-commands.js'
const props = defineProps({ workflow: Object, job: Object })
const emit = defineEmits(['close', 'created'])
const draft = reactive({ name: '', nodes: props.job.nodes, priority: props.job.priority, command: '', authorization: '' })
const training = reactive({})
const evaluation = reactive({})
const ready = ref(false)
const pending = ref(false)
const error = ref('')
const automatic = ref(false)
let requestId = '', fingerprint = ''
onMounted(async () => {
  try {
    const [config, defaults] = await Promise.all([apiRequest(`workflows/${props.workflow.id}/configuration`), apiRequest('workflow-defaults')])
    automatic.value = defaults.auth_mode === 'iam'
    const strategy = config.strategies.find(s => s.id === props.job.strategy_id)
    draft.command = strategy?.[`${props.job.module}_command`] || config.commands?.[props.job.module] || defaults.commands[props.job.module]
    const t = strategy?.training || config.training
    for (const key of ['token_budget', 'device_batch_size', 'devices_per_node', 'eval_every', 'core_metric_every']) if (t[key] !== undefined) training[key] = t[key]
    if (!t.token_budget) training.num_iterations = t.num_iterations || 0
    Object.assign(evaluation, { devices_per_node: config.evaluation.devices_per_node, core_eval_batch_size: config.evaluation.core_eval_batch_size })
    ready.value = true
  } catch (reason) { error.value = reason.message }
})
async function submit() {
  pending.value = true; error.value = ''
  try {
    validateJobCommands([{ owner: draft, commandKey: 'command', label: '重试作业' }])
    const body = { ...draft, ...(props.job.module === 'training' ? { training: { ...training } } : {}),
      ...(props.job.module === 'evaluation' ? { evaluation: { ...evaluation } } : {}) }
    if (JSON.stringify(body) !== fingerprint) {
      fingerprint = JSON.stringify(body)
      requestId = window.crypto?.randomUUID?.() || `retry_${Date.now()}_${Math.random().toString(36).slice(2)}`
    }
    const result = await apiRequest(`workflows/${props.workflow.id}/jobs/${props.job.key}/retry`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, request_id: requestId }),
    })
    emit('created', result.id)
  } catch (reason) { error.value = reason.message }
  finally { pending.value = false }
}
</script>
<template>
  <form class="config-block" @submit.prevent="submit">
    <h3>作业重试 · {{ job.strategy_name || '汇总评测' }}</h3>
    <p>直接复用成功的前序输出，仅重建当前作业及其后续依赖。原实验和其他成功模型保持不变。</p>
    <p v-if="job.input_obs_uri" class="break-path">复用输入：{{ job.input_obs_uri }}</p>
    <div class="form-grid two-cols">
      <label class="field"><span>新作业名称</span><input v-model="draft.name" placeholder="留空按时间命名" maxlength="64" /></label>
      <label class="field"><span>节点数</span><input v-model.number="draft.nodes" type="number" min="1" max="16" required /></label>
      <label class="field"><span>任务优先级</span><select v-model.number="draft.priority"><option :value="1">1</option><option :value="2">2</option><option :value="3">3</option></select></label>
      <template v-if="job.module === 'training'">
        <label v-for="[key, label, min] in [['token_budget', '训练 Token 预算', 1], ['devices_per_node', '每节点 NPU 数', 1], ['device_batch_size', '单卡批量大小', 1], ['eval_every', '验证损失检查间隔', -1], ['core_metric_every', '任务评测间隔', -1]]" :key="key" class="field"><span>{{ label }}</span><input v-model.number="training[key]" type="number" :min="min" /></label>
      </template>
      <template v-if="job.module === 'evaluation'">
        <label class="field"><span>每节点 NPU 数</span><input v-model.number="evaluation.devices_per_node" type="number" min="1" max="8" /></label>
        <label class="field"><span>评测批量大小</span><input v-model.number="evaluation.core_eval_batch_size" type="number" min="1" /></label>
      </template>
    </div>
    <label class="field"><span>command</span><textarea v-model="draft.command" rows="7" style="width:100%"></textarea></label>
    <label v-if="!automatic" class="field"><span>Authorization</span><input v-model="draft.authorization" type="password" autocomplete="off" /></label>
    <p v-else>提交时自动获取 Authorization。</p>
    <p v-if="error" class="error-message">{{ error }}</p>
    <button class="button secondary" type="button" :disabled="pending" @click="emit('close')">取消</button>
    <button class="button primary" type="submit" :disabled="!ready || pending">{{ pending ? '提交中…' : '提交作业重试' }}</button>
  </form>
</template>
