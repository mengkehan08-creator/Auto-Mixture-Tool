<script setup>
import { CheckCircle2, LoaderCircle, Rocket } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { strategyOptions } from '../../data/defaults'
import { apiRequest } from '../../api'
import { fieldLabels, submissionFailed } from '../../workflow-state'
import { normalizeEvaluationTasks } from '../../evaluation-selection.js'

const props = defineProps({ strategies: Array, training: Object, evaluation: Object, runtime: Object })
const status = ref('idle')
const error = ref('')
const workflows = ref([])
const connectionError = ref('')
const validation = ref(null)
const authMode = ref('manual')
const pendingId = ref('')
const emit = defineEmits(['created'])
let requestId = ''
let submittedBody = ''
let timer = null

const strategyNames = computed(() => props.strategies.map((strategy) => strategyOptions.find((option) => option.value === strategy.type)?.label).join('、'))

function normalizedStrategies() {
  return props.strategies.map((item) => ({
    id: item.type === 'manual' ? `manual_${item.id}` : item.type,
    type: item.type,
    name: item.name,
    seed: item.seed,
    proxy_experiments: item.proxyExperiments,
    proxy_steps: item.proxySteps,
    search_count: item.searchCount,
    devices_per_node: item.devicesPerNode,
    ratios: item.ratios,
    script_obs_uri: item.source === 'script' && item.scriptInput !== 'upload' ? item.scriptObsUri : '',
    ...(item.source === 'script' && item.scriptInput === 'upload' ? { script_upload: item.scriptUpload || { name: '', content: '' } } : {}),
    script_config: item.scriptConfig || {},
  }))
}

function requestBody() {
  return {
    ...(props.runtime.reuse ? { reuse: props.runtime.reuse } : {}),
    ...(props.runtime.commands ? { commands: props.runtime.commands } : {}),
    modelarts: props.runtime.modelarts,
    priority: props.runtime.priority ?? 1,
    offline_resources: props.runtime.offlineResources,
    experiment_name: props.runtime.experimentName || null,
    input_data_obs_uri: props.runtime.inputDataObsUri,
    output_root_obs_uri: props.runtime.outputRootObsUri,
    mixing_nodes: props.runtime.mixingNodes,
    training_nodes: props.training.nodes,
    evaluation_nodes: props.evaluation.nodes,
    strategies: normalizedStrategies(),
    training: {
      output_obs_uri: props.training.outputObsUri,
      framework: 'nanochat', model: props.training.model,
      base_model_tag: props.training.baseModelTag,
      target_param_data_ratio: props.training.targetParamDataRatio,
      devices_per_node: props.training.devicesPerNode,
      token_budget: props.training.tokenBudget,
      device_batch_size: props.training.deviceBatchSize,
      eval_every: props.training.evalEvery,
      core_metric_every: props.training.coreMetricEvery,
    },
    evaluation: { obs_packages: props.evaluation.dataset.enabled && props.evaluation.dataset.source === 'obs' ? props.evaluation.obsPackages : [], automatic_api_requested: props.evaluation.api.enabled, output_obs_uri: props.evaluation.outputObsUri, devices_per_node: props.evaluation.devicesPerNode, core_eval_batch_size: props.evaluation.coreEvalBatchSize, max_per_task: -1, datasets: props.evaluation.dataset.enabled ? normalizeEvaluationTasks(props.evaluation.dataset.names) : [] },
    resources: {
      code_obs_uri: props.runtime.codeObsUri,
      nanochat_repo_obs_uri: props.training.frameworkObsUri,
      nanochat_model_obs_uri: props.training.modelObsUri,
      quadmix_tokenizer_obs_uri: props.runtime.quadmixTokenizerObsUri,
      proxy_validation_obs_uri: props.runtime.proxyValidationObsUri,
      python_wheels_obs_uri: props.runtime.pythonWheelsObsUri,
      ...Object.fromEntries(props.runtime.offlineResources.filter(r => r.role).map(r => [r.role, r.uri])),
      eval_bundle_obs_uri: props.evaluation.dataset.source === 'obs' ? props.evaluation.dataset.obsUri :
        (props.runtime.offlineResources.find(r => r.role === 'eval_bundle_obs_uri')?.uri || props.runtime.evalBundleObsUri),
    },
  }
}

async function loadWorkflows() {
  try {
    workflows.value = await apiRequest('workflows')
    connectionError.value = ''
    const pending = workflows.value.find(w => w.id === pendingId.value)
    if (pending && submissionFailed(pending)) {
      error.value = pending.message || '作业创建失败，请检查配置。'
      status.value = 'failed'
      pendingId.value = ''
    } else if (pending?.jobs.some(job => job.id)) {
      pendingId.value = ''
      status.value = 'success'
      emit('created', pending.id)
    }
  } catch (reason) { connectionError.value = reason.message }
}

async function checkConfiguration() {
  error.value = ''
  validation.value = null
  try {
    if (!props.runtime.commands) throw new Error('启动命令尚未加载，请点击重新加载默认命令。')
    validation.value = await apiRequest('workflows/validate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody()),
    })
    if (!validation.value.ready) throw new Error(`请补充 ModelArts 配置：${validation.value.missing_settings.map(key => fieldLabels[key] || key).join('、')}`)
    return true
  } catch (reason) {
    error.value = reason.message
    return false
  }
}

async function submit() {
  status.value = 'loading'
  error.value = ''
  try {
    if (!await checkConfiguration()) { status.value = 'failed'; return }
    const config = requestBody()
    const fingerprint = JSON.stringify(config)
    if (fingerprint !== submittedBody) {
      requestId = window.crypto?.randomUUID?.() || `request_${Date.now()}_${Math.random().toString(36).slice(2)}`
      submittedBody = fingerprint
    }
    const body = await apiRequest('workflows', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...config, request_id: requestId }),
    })
    pendingId.value = body.id
    await loadWorkflows()
  } catch (reason) {
    status.value = 'failed'
    error.value = reason.message || String(reason)
  }
}

async function loadCommands(reset = false) {
  try {
    const defaults = await apiRequest('workflow-defaults')
    authMode.value = defaults.auth_mode || 'manual'
    if (authMode.value === 'iam') props.runtime.modelarts.authorization = ''
    if (reset || !props.runtime.commands) props.runtime.commands = defaults.commands
    else if (!props.runtime.commands.evaluation) props.runtime.commands.evaluation = defaults.commands.evaluation
    for (const [key, value] of Object.entries(defaults.modelarts || {})) {
      if (!props.runtime.modelarts[key]) props.runtime.modelarts[key] = value
    }
    error.value = ''
  } catch (reason) { error.value = `加载启动命令失败：${reason.message}` }
}
onMounted(() => { loadCommands(); loadWorkflows(); timer = window.setInterval(loadWorkflows, 3000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <section class="step-panel">
    <div class="section-title-row"><div><h2>任务配置</h2><p v-if="runtime.reuse">{{ runtime.reuse.stage === 'evaluation' ? '本次仅提交 1 个评测作业，复用已有模型。' : `本次提交 ${evaluation.dataset.enabled ? 2 : 1} 个作业：训练${evaluation.dataset.enabled ? ' → 评测' : ''}，复用已有采样集。` }}</p><p v-else>评测集启用且选择了任务或 OBS 评测包时提交三个作业，否则只提交配比和训练作业。</p></div></div>
    <p v-if="evaluation.api.enabled" class="path-preview" role="status">自动评估暂未接入：本次不会执行自动评估，也不会创建自动评估作业。</p>
    <h3>ModelArts 作业配置</h3>
    <p class="path-preview">已填入脚本默认配置，可编辑。</p>
    <div class="form-grid two-cols">
      <label v-for="key in ['endpoint', 'region', 'workspace_id', 'workspace_name', 'image_url', 'image_repo_id', 'flavor_id', 'pool_id']" :key="key" class="field"><span>{{ fieldLabels[key] }}</span><input v-model="runtime.modelarts[key]" autocomplete="off" /></label>
      <label class="field"><span>priority（任务优先级）</span><select v-model.number="runtime.priority"><option :value="1">1（默认）</option><option :value="2">2</option><option :value="3">3（需高优先级权限）</option></select><small>同时用于配比和训练作业。</small></label>
      <label v-if="authMode === 'iam'" class="field"><span>Authorization</span><input value="自动获取（提交时执行）" readonly /><small>已启用私有 IAM 配置；Token 仅用于后端请求，不在页面显示。</small></label>
      <label v-else class="field"><span>Authorization</span><input v-model="runtime.modelarts.authorization" type="password" autocomplete="off" /><small>当前为手动模式。配置 AMT_IAM_PROVIDER 并重启后端，可自动获取。</small></label>
    </div>
    <div class="review-grid">
      <article><span>training.output_obs_uri</span><strong class="break-path">{{ training.outputObsUri || '沿用实验输出目录' }}</strong><small>模型与检查点 · 自动追加 runs/实验名称/</small></article>
      <article><span>evaluation.output_obs_uri</span><strong class="break-path">{{ evaluation.outputObsUri || '沿用实验输出目录' }}</strong><small>评测与对比报告 · 自动追加 runs/实验名称/</small></article>
      <article><span>配比作业</span><strong>{{ strategyNames }}</strong><small>{{ runtime.reuse ? '复用原实验采样集，不提交' : `${runtime.mixingNodes} 节点 · 先校验再生成全部采样集` }}</small></article>
      <article><span>训练作业</span><strong>{{ training.framework }}</strong><small>{{ runtime.reuse?.stage === 'evaluation' ? '复用原实验模型，不提交' : `${training.nodes} 节点 · 依次训练全部采样集` }}</small></article>
      <article><span>evaluation_nodes</span><strong>{{ evaluation.dataset.enabled ? `${evaluation.nodes} 节点` : '未启用评测' }}</strong><small>模型输入自动使用前序训练输出</small></article>
      <article><span>training.token_budget</span><strong>{{ Number(training.tokenBudget).toLocaleString() }} Token</strong><small>各配比模型共用训练预算</small></article>
      <article><span>输出根目录</span><strong class="break-path">{{ runtime.outputRootObsUri }}</strong><small>按实验名称隔离 mixing / sampled / training</small></article>
    </div>
    <div class="config-block">
      <h3>command</h3>
      <p>默认命令已包含离线环境检查，可编辑。请勿在命令中填写凭据。</p>
      <template v-if="runtime.commands">
        <label v-if="!runtime.reuse" class="field"><span>command（配比作业）</span><textarea v-model="runtime.commands.mixing" rows="8" style="width:100%;font-family:monospace" spellcheck="false"></textarea></label>
        <label v-if="runtime.reuse?.stage !== 'evaluation'" class="field"><span>command（训练作业）</span><textarea v-model="runtime.commands.training" rows="8" style="width:100%;font-family:monospace" spellcheck="false"></textarea></label>
        <label class="field"><span>command（评测作业）</span><textarea v-model="runtime.commands.evaluation" rows="8" style="width:100%;font-family:monospace" spellcheck="false"></textarea></label>
      </template>
      <button class="button secondary" type="button" @click="loadCommands(true)">{{ runtime.commands ? '恢复默认命令' : '重新加载默认命令' }}</button>
    </div>

    <p class="path-preview">提交会创建收费云作业，结果保存到指定 OBS 目录下的独立实验子目录。</p>
    <button class="button secondary" type="button" :disabled="status === 'loading'" @click="checkConfiguration">检查配置（不创建作业）</button>
    <p v-if="validation?.ready" class="path-preview">配置检查通过。{{ validation.message }}</p>
    <button class="button submit-button" type="button" :disabled="status === 'loading' || (status === 'success' && submittedBody === JSON.stringify(requestBody()))" @click="submit">
      <LoaderCircle v-if="status === 'loading'" class="spin" :size="18" /><Rocket v-else :size="18" />
      {{ status === 'loading' ? '正在检查并提交实验…' : '提交到 ModelArts' }}
    </button>
    <p v-if="error" class="error-message">{{ error }}</p>
    <article v-if="status === 'success'" class="submit-result"><CheckCircle2 :size="25" /><div><strong>实验已受理</strong><span>第二个作业将在第一个成功后自动提交。</span></div></article>
    <p v-if="connectionError" class="error-message">状态服务连接失败：{{ connectionError }}。请在左侧实验作业核对提交结果，勿重复提交。</p>
  </section>
</template>
