<script setup>
import { onMounted, reactive, ref } from 'vue'
import { apiRequest } from '../api'
import { validateJobCommands } from '../job-commands.js'
import { normalizeEvaluationTasks, stemTasks } from '../evaluation-selection.js'
import ConfirmationDialog from './ConfirmationDialog.vue'
const confirming = ref(false)
const props = defineProps({ workflow: Object, job: Object })
const emit = defineEmits(['close', 'created', 'busy'])
const draft = reactive({ name: '', nodes: props.job.nodes, priority: props.job.priority, command: '', authorization: '' })
const training = reactive({})
const evaluation = reactive({})
const resources = reactive({})
const modelarts = reactive({})
const resourceFields = [['code_obs_uri', '工具代码 OBS 地址'], ['nanochat_repo_obs_uri', 'NanoChat 代码 OBS 地址'],
  ['python_wheels_obs_uri', '安装包 OBS 地址'], ['eval_bundle_obs_uri', '内置评测资源 OBS 地址']]
const modelartsFields = ['endpoint', 'region', 'workspace_id', 'workspace_name', 'image_url', 'image_repo_id', 'flavor_id', 'pool_id']
const ready = ref(false)
const pending = ref(false)
const error = ref('')
const automatic = ref(false)
let requestId = '', fingerprint = ''
async function load() {
  error.value = ''
  try {
    const [config, defaults] = await Promise.all([apiRequest(`workflows/${props.workflow.id}/configuration`), apiRequest('workflow-defaults')])
    automatic.value = defaults.auth_mode === 'iam'
    const strategy = config.strategies?.find(s => s.id === props.job.strategy_id)
    draft.command = strategy?.[`${props.job.module}_command`] || config.commands?.[props.job.module] || defaults.commands?.[props.job.module] || ''
    draft.output_root_obs_uri = config.output_root_obs_uri
    const t = { ...config.training, ...strategy?.training }
    for (const key of ['token_budget', 'device_batch_size', 'devices_per_node', 'eval_every', 'core_metric_every']) if (t[key] !== undefined) training[key] = t[key]
    if (!t.token_budget) training.num_iterations = t.num_iterations || 0
    training.output_obs_uri = t.output_obs_uri || ''
    Object.assign(evaluation, config.evaluation, { datasets: normalizeEvaluationTasks(config.evaluation?.datasets || []), obs_packages: config.evaluation?.obs_packages || [] })
    for (const [key] of resourceFields) if (config.resources?.[key] !== undefined) resources[key] = config.resources[key]
    if (props.job.module === 'training' && strategy?.training_framework_source === 'obs') resources.nanochat_repo_obs_uri = strategy.training_framework_obs_uri
    for (const key of modelartsFields) modelarts[key] = config.modelarts?.[key] ?? defaults.modelarts?.[key] ?? ''
    ready.value = true
  } catch (reason) { error.value = reason.message }
}
onMounted(load)
async function submit(confirmed = false) {
  if (pending.value || !ready.value) return
  if (confirmed !== true) { confirming.value = true; return }
  confirming.value = false
  pending.value = true; error.value = ''
  emit('busy', true)
  try {
    validateJobCommands([{ owner: draft, commandKey: 'command', label: '重试作业' }])
    const body = { ...draft, resources: { ...resources }, modelarts: { ...modelarts },
      ...(props.job.module === 'training' ? { training: { ...training } } : {}),
      ...(props.job.module === 'evaluation' ? { evaluation: { ...evaluation } } : {}) }
    if (body.training && (body.training.token_budget === '' || body.training.token_budget == null)) delete body.training.token_budget
    if (JSON.stringify(body) !== fingerprint) {
      fingerprint = JSON.stringify(body)
      requestId = window.crypto?.randomUUID?.() || `retry_${Date.now()}_${Math.random().toString(36).slice(2)}`
    }
    const result = await apiRequest(`workflows/${props.workflow.id}/jobs/${props.job.key}/retry`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, request_id: requestId }),
    })
    emit('created', result.id)
  } catch (reason) { error.value = reason.message }
  finally { pending.value = false; emit('busy', false) }
}
</script>
<template>
  <form class="config-block" @submit.prevent="submit">
    <ConfirmationDialog v-if="confirming" title="确认阶段重试？" message="将复用前序成功输出，创建当前阶段及后续依赖的新云作业，可能产生费用。" confirm-label="确认提交重试" @cancel="confirming = false" @confirm="submit(true)" />
    <div class="section-title-row"><h3>{{ { mixing: '配比阶段重试', training: '训练阶段重试', evaluation: '评测阶段重试' }[job.module] }} · {{ job.strategy_name || '汇总评测' }}</h3><button class="button secondary" type="button" autofocus :disabled="pending" @click="emit('close')">取消重试</button></div>
    <p>直接复用成功的前序输出，仅重建当前作业及其后续依赖。原实验和其他成功模型保持不变。</p>
    <p v-if="job.input_obs_uri" class="break-path">复用输入：{{ job.input_obs_uri }}</p>
    <div v-else-if="job.module === 'evaluation'" class="output-paths"><strong>复用已成功训练的模型（不重新训练）</strong><span v-for="item in workflow.jobs.filter(j => j.module === 'training')" :key="item.key">{{ item.strategy_name || item.name }}：{{ item.outputs?.models || '沿用原实验模型清单' }}</span></div>
    <p v-if="!ready" role="status">{{ error ? '原作业配置加载失败，请重试。' : '正在读取原作业参数和地址…' }}</p>
    <p v-if="error" class="error-message" role="alert">{{ error }}</p>
    <button v-if="error && !ready" class="button secondary" type="button" @click="load">重新加载配置</button>
    <fieldset v-if="ready" :disabled="pending">
    <div class="form-grid two-cols">
      <label class="field"><span>新作业名称</span><input v-model="draft.name" placeholder="留空按时间命名" maxlength="64" /></label>
      <label class="field"><span>节点数</span><input v-model.number="draft.nodes" type="number" min="1" max="16" required /></label>
      <label class="field"><span>任务优先级</span><select v-model.number="draft.priority"><option :value="1">1</option><option :value="2">2</option><option :value="3">3</option></select></label>
      <template v-if="job.module === 'training'">
        <label v-for="[key, label, min] in [['token_budget', '训练 Token 预算', 1], ['devices_per_node', '每节点 NPU 数', 1]]" :key="key" class="field"><span>{{ label }}</span><input v-model.number="training[key]" type="number" :min="min" :required="key === 'devices_per_node'" @input="key === 'token_budget' && (training.num_iterations = 0)" /></label>
        <label class="field"><span>模型输出 OBS 目录</span><input v-model="training.output_obs_uri" placeholder="留空沿用输出根目录" /></label>
      </template>
      <template v-if="job.module === 'evaluation'">
        <label class="field"><span>每节点 NPU 数</span><input v-model.number="evaluation.devices_per_node" type="number" min="1" max="8" /></label>
        <label class="field"><span>评测批量大小</span><input v-model.number="evaluation.core_eval_batch_size" type="number" min="1" /></label>
        <label class="field"><span>报告输出 OBS 目录</span><input v-model="evaluation.output_obs_uri" placeholder="留空沿用输出根目录" /></label>
      </template>
    </div>
    <section v-if="job.module === 'evaluation'" class="config-block">
      <h3>评测集</h3>
      <div class="retry-tasks"><label v-for="task in [...new Set([...stemTasks, ...evaluation.datasets])]" :key="task"><input v-model="evaluation.datasets" type="checkbox" :value="task" />{{ task }}</label></div>
      <div v-for="(item, index) in evaluation.obs_packages" :key="index" class="form-grid two-cols">
        <label class="field"><span>评测包名称</span><input v-model="item.name" required /></label>
        <label class="field"><span>评测包 OBS 地址</span><input v-model="item.obs_uri" required /></label>
        <button class="button secondary" type="button" @click="evaluation.obs_packages.splice(index, 1)">删除</button>
      </div>
      <button class="button secondary" type="button" @click="evaluation.obs_packages.push({ name: '', obs_uri: '' })">增加评测包</button>
    </section>
    <section class="config-block">
      <h3>资源与输出地址</h3>
      <div class="form-grid two-cols">
        <label v-for="[key, label] in resourceFields.filter(([key]) => key in resources)" :key="key" class="field"><span>{{ label }}</span><input v-model="resources[key]" required /></label>
        <label class="field"><span>输出根目录</span><input v-model="draft.output_root_obs_uri" required /></label>
      </div>
      <small>新输出按重试实验隔离，保留原模型和报告；前序输入地址保持不变。</small>
    </section>
    <details class="config-block"><summary>ModelArts 任务配置</summary><div class="form-grid two-cols">
      <label v-for="key in modelartsFields" :key="key" class="field"><span>{{ key }}</span><input v-model="modelarts[key]" /></label>
    </div></details>
    <label class="field"><span>command</span><textarea v-model="draft.command" rows="7" style="width:100%"></textarea></label>
    <label v-if="!automatic" class="field"><span>Authorization</span><input v-model="draft.authorization" type="password" autocomplete="off" /></label>
    <p v-else>提交时自动获取 Authorization。</p>
    </fieldset>
    <button class="button primary" type="submit" :disabled="!ready || pending">{{ pending ? '提交中…' : '提交作业重试' }}</button>
  </form>
</template>
<style scoped>
fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.retry-tasks { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
.retry-tasks label { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.retry-tasks input { width: 18px; height: 18px; min-height: 18px; flex: 0 0 18px; margin: 0; }
summary { cursor: pointer; margin-bottom: 16px; }
</style>
