<script setup>
import { CheckCircle2, LoaderCircle, Rocket } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { strategyOptions } from '../../data/defaults'
import { apiRequest } from '../../api'
import { fieldLabels, submissionFailed } from '../../workflow-state'
import { normalizeEvaluationTasks } from '../../evaluation-selection.js'
import { initializeJobCommands, refreshJobCommands, validateJobCommands } from '../../job-commands.js'
import { trainingParameters } from '../../data/defaults'
import { strategyId, strategyLabel, strategyNameHint, trainingNameHint } from '../../strategy-names'

const props = defineProps({ strategies: Array, training: Object, evaluation: Object, runtime: Object })
const status = ref('idle')
const error = ref('')
const workflows = ref([])
const connectionError = ref('')
const validation = ref(null)
const authMode = ref('manual')
const pendingId = ref('')
const defaultCommands = ref(null)
const emit = defineEmits(['created'])
let requestId = ''
let submittedBody = ''
let timer = null
let commandTimer = null, commandVersion = 0
const commandsPending = ref(false)
const commandError = ref('')
const commandSettings = computed(() => ({
  image_url: props.runtime.modelarts.image_url,
  offline_resources: props.runtime.offlineResources,
  input_data_obs_uri: props.runtime.inputDataObsUri,
  model_obs_uri: props.training.modelObsUri,
  framework_obs_uri: props.training.frameworkObsUri,
  eval_bundle_obs_uri: props.evaluation.dataset.source === 'obs' ? props.evaluation.dataset.obsUri :
    (props.runtime.offlineResources.find(r => r.role === 'eval_bundle_obs_uri')?.uri || props.runtime.evalBundleObsUri),
  eval_packages: props.evaluation.dataset.source === 'obs' ? props.evaluation.obsPackages : [],
  output_obs_uri: props.runtime.outputRootObsUri,
  model_output_obs_uri: props.training.outputObsUri,
  report_output_obs_uri: props.evaluation.outputObsUri,
}))
async function updateCommands() {
  const version = ++commandVersion
  commandsPending.value = true
  commandError.value = ''
  try {
    const result = await apiRequest('workflow-commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(commandSettings.value) })
    if (version !== commandVersion) return
    refreshJobCommands(props.strategies, props.runtime, result.commands)
    defaultCommands.value = result.commands
  } catch (reason) { if (version === commandVersion) commandError.value = `命令更新失败：${reason.message}` }
  finally { if (version === commandVersion) commandsPending.value = false }
}
watch(commandSettings, () => { commandVersion++; commandsPending.value = true; clearTimeout(commandTimer); commandTimer = setTimeout(updateCommands, 350) }, { deep: true })
watch(() => [props.runtime, props.training, props.evaluation, props.strategies], () => { validation.value = null }, { deep: true })

const strategyNames = computed(() => props.strategies.map((strategy) => strategyOptions.find((option) => option.value === strategy.type)?.label).join('、'))
const evaluationEnabled = computed(() => props.evaluation.dataset.enabled && (props.evaluation.dataset.names.length || props.evaluation.obsPackages.length))
const jobPlan = computed(() => [
  ...props.strategies.flatMap(s => [
    { key: `mixing-${s.id}`, owner: s, commandKey: 'mixingCommand', module: 'mixing', label: `${strategyLabel(s)} · 配比`, name: s.mixingJobName, nameHint: strategyNameHint(s), nodes: s.mixingNodes, priority: s.mixingPriority, depends: '无，可立即提交' },
    { key: `training-${s.id}`, owner: s, commandKey: 'trainingCommand', module: 'training', label: `${strategyLabel(s)} · 训练`, name: s.trainingJobName, nameHint: trainingNameHint(s), nodes: s.trainingNodes, priority: s.trainingPriority, depends: `${strategyLabel(s)} 配比成功` },
  ]),
  ...(evaluationEnabled.value ? [{ key: 'evaluation', owner: props.runtime.commands || {}, commandKey: 'evaluation', module: 'evaluation', label: '汇总评测', name: props.evaluation.jobName, nodes: props.evaluation.nodes, priority: props.evaluation.priority, depends: '本次全部训练成功' }] : []),
])

function normalizedStrategies() {
  return props.strategies.map((item) => ({
    id: strategyId(item),
    type: item.type,
    name: item.name,
    seed: item.seed,
    proxy_experiments: item.proxyExperiments,
    proxy_steps: item.proxySteps,
    ...(item.type === 'quadmix' ? { sampling_bounds: Object.fromEntries(Object.entries(item.samplingBounds).map(([key, range]) => [key, [0, range[1]]])) } : {}),
    search_count: item.searchCount,
    devices_per_node: 8,
    mixing_nodes: item.mixingNodes, training_nodes: item.trainingNodes,
    mixing_job_name: item.mixingJobName, training_job_name: item.trainingJobName,
    mixing_priority: item.mixingPriority, training_priority: item.trainingPriority,
    training_framework_source: props.training.frameworkSource,
    training_framework_obs_uri: props.training.frameworkSource === 'obs' ? props.training.frameworkObsUri : '',
    mixing_command: item.mixingCommand, training_command: item.trainingCommand,
    model_name: item.modelName, training: trainingParameters(props.training),
    ratios: item.ratios,
    script_obs_uri: item.source === 'script' && item.scriptInput !== 'upload' ? item.scriptObsUri : '',
    ...(item.source === 'script' && item.scriptInput === 'upload' ? { script_upload: item.scriptUpload || { name: '', content: '' } } : {}),
    script_config: item.scriptConfig || {},
  }))
}

function requestBody() {
  return {
    execution_mode: 'parallel',
    max_active_jobs: props.runtime.maxActiveJobs ?? 8,
    ...(props.runtime.commands ? { commands: {
      ...props.runtime.commands,
      evaluation: evaluationEnabled.value ? props.runtime.commands.evaluation : (defaultCommands.value?.evaluation || props.runtime.commands.evaluation),
    } } : {}),
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
      devices_per_node: 8,
      token_budget: props.training.tokenBudget,
      device_batch_size: props.training.deviceBatchSize,
      eval_every: props.training.evalEvery,
      core_metric_every: props.training.coreMetricEvery,
    },
    evaluation: { comparison_policy: 'allow-differences', job_name: props.evaluation.jobName, priority: props.evaluation.priority, model_ids: props.evaluation.dataset.enabled ? props.evaluation.modelIds : [], obs_packages: props.evaluation.dataset.enabled && props.evaluation.dataset.source === 'obs' ? props.evaluation.obsPackages : [], automatic_api_requested: props.evaluation.api.enabled, output_obs_uri: props.evaluation.outputObsUri, devices_per_node: 8, core_eval_batch_size: props.evaluation.coreEvalBatchSize, max_per_task: -1, datasets: props.evaluation.dataset.enabled ? normalizeEvaluationTasks(props.evaluation.dataset.names) : [] },
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
    if (!props.runtime.datasetEstimate?.ready) throw new Error('输入数据尚未自动校验通过，请返回配比配置等待校验完成或查看失败原因。')
    if (commandsPending.value) throw new Error('启动命令正在更新，请稍后检查或提交。')
    if (commandError.value) throw new Error(commandError.value)
    if (!props.runtime.commands) throw new Error('启动命令尚未加载，请点击重新加载默认命令。')
    validateJobCommands(jobPlan.value)
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

async function loadCommands() {
  try {
    const defaults = await apiRequest('workflow-defaults')
    authMode.value = defaults.auth_mode || 'manual'
    if (authMode.value === 'iam') props.runtime.modelarts.authorization = ''
    defaultCommands.value = defaults.commands
    initializeJobCommands(props.strategies, props.runtime, defaults.commands)
    for (const [key, value] of Object.entries(defaults.modelarts || {})) {
      if (!props.runtime.modelarts[key]) props.runtime.modelarts[key] = value
    }
    clearTimeout(commandTimer)
    await updateCommands()
    error.value = ''
  } catch (reason) { error.value = `加载启动命令失败：${reason.message}` }
}
onMounted(() => { loadCommands(); loadWorkflows(); timer = window.setInterval(loadWorkflows, 3000) })
onBeforeUnmount(() => { window.clearInterval(timer); clearTimeout(commandTimer); commandVersion++ })
</script>

<template>
  <section class="step-panel">
    <div class="section-title-row"><div><h2>任务配置</h2><p>本次计划 {{ jobPlan.length }} 个独立作业。每个策略配比成功即启动训练，全部训练成功后汇总评测。</p></div></div>
    <div class="config-block">
      <h3>作业提交清单</h3>
      <div class="job-plan-scroll"><table class="job-plan"><thead><tr><th>module</th><th>name</th><th>node_count</th><th>priority</th><th>depends_on</th></tr></thead>
        <tbody><tr v-for="(job, index) in jobPlan" :key="index"><td>{{ job.label }}</td><td>{{ job.name || job.nameHint || '自动按时间命名' }}</td><td>{{ job.nodes }}</td><td>{{ job.priority }}</td><td>{{ job.depends }}</td></tr></tbody>
      </table></div>
      <label class="field"><span>max_active_jobs</span><input v-model.number="runtime.maxActiveJobs" type="number" min="1" max="1000" step="1" /><small>本实验同时已提交或运行的作业数，默认 8。其余在工具内等待，完成后自动补交；不限制策略总数。</small></label>
      <p v-if="evaluationEnabled">评测模型：本次 {{ strategies.length }} 个＋历史 {{ evaluation.modelIds.length }} 个。</p>
    </div>
    <p v-if="evaluation.api.enabled" class="path-preview" role="status">自动评估暂未接入：本次不会执行自动评估，也不会创建自动评估作业。</p>
    <div class="section-title-row modelarts-heading"><div><h3>ModelArts 作业配置</h3><p>已填入脚本默认值，可按资源池与镜像调整。</p></div></div>
    <div class="form-grid two-cols">
      <label v-for="key in ['endpoint', 'region', 'workspace_id', 'workspace_name', 'image_url', 'image_repo_id', 'flavor_id', 'pool_id']" :key="key" class="field"><span>{{ fieldLabels[key] }}</span><textarea rows="2" v-model="runtime.modelarts[key]" autocomplete="off" ></textarea></label>
      <label v-if="authMode === 'iam'" class="field"><span>Authorization</span><input value="自动获取（提交时执行）" readonly /><small>已启用私有 IAM 配置；Token 仅用于后端请求，不在页面显示。</small></label>
      <label v-else class="field"><span>Authorization</span><input v-model="runtime.modelarts.authorization" type="password" autocomplete="off" /><small>当前为手动模式。配置 AMT_IAM_PROVIDER 并重启后端，可自动获取。</small></label>
    </div>
    <div class="review-grid">
      <article><span>training.output_obs_uri</span><strong class="break-path">{{ training.outputObsUri || '沿用实验输出目录' }}</strong><small>模型与检查点 · 自动追加 runs/实验名称/</small></article>
      <article><span>evaluation.output_obs_uri</span><strong class="break-path">{{ evaluation.outputObsUri || '沿用实验输出目录' }}</strong><small>评测与对比报告 · 自动追加 runs/实验名称/</small></article>
      <article><span>配比作业</span><strong>{{ strategyNames }}</strong><small>{{ strategies.length }} 个独立作业 · 各自校验与采样</small></article>
      <article><span>训练作业</span><strong>{{ training.framework }}</strong><small>{{ strategies.length }} 个独立作业 · 可并行训练</small></article>
      <article><span>evaluation_nodes</span><strong>{{ evaluation.dataset.enabled ? `${evaluation.nodes} 节点` : '未启用评测' }}</strong><small>模型输入自动使用前序训练输出</small></article>
      <article><span>training.token_budget</span><strong>{{ Number(training.tokenBudget).toLocaleString() }} Token</strong><small>全部策略共用训练预算</small></article>
      <article><span>输出根目录</span><strong class="break-path">{{ runtime.outputRootObsUri }}</strong><small>按实验名称隔离 mixing / sampled / training</small></article>
    </div>
    <div class="job-commands">
      <h3>作业启动命令</h3>
      <p>默认命令随镜像、挂载配置自动更新。手动编辑后保留该作业命令，点击恢复可重新跟随配置。当前支持 Python 3.11 / Ascend 镜像。</p>
      <p v-if="commandsPending" role="status">正在更新命令…</p>
      <p v-if="commandError" role="alert" class="error-message">{{ commandError }} <button type="button" class="button secondary" @click="updateCommands">重试更新</button></p>
      <button v-if="!defaultCommands" class="button secondary" type="button" @click="loadCommands">重新加载默认命令</button>
      <article v-for="job in jobPlan" :key="job.key" class="config-block">
        <header class="job-command-heading">
          <div><h3>{{ job.label }}</h3><small>name：{{ job.name || job.nameHint || '自动按时间命名' }} · node_count：{{ job.nodes }} · priority：{{ job.priority }}</small></div>
          <button class="button secondary" type="button" :disabled="!defaultCommands || status === 'loading'" @click="job.owner[job.commandKey] = defaultCommands[job.module]">恢复此作业默认命令</button>
        </header>
        <p v-if="defaultCommands && job.owner[job.commandKey] !== defaultCommands[job.module]" class="path-preview">手动命令：不会被配置更新覆盖，请核对挂载及解释器；恢复默认可继续自动联动。</p>
        <label class="field"><span>command</span><textarea v-model="job.owner[job.commandKey]" rows="8" :disabled="status === 'loading' || job.owner[job.commandKey] == null" spellcheck="false" placeholder="正在加载默认命令…"></textarea></label>
      </article>
    </div>

    <p class="path-preview">提交会创建收费云作业，结果保存到指定 OBS 目录下的独立实验子目录。</p>
    <p v-if="validation?.ready" class="success-message" role="status">配置检查通过。{{ validation.message }}</p>
    <div class="submission-actions" :aria-busy="status === 'loading'">
      <button class="button secondary" type="button" :disabled="status === 'loading'" @click="checkConfiguration">检查配置（不创建作业）</button>
      <button class="button submit-button" type="button" :disabled="!runtime.datasetEstimate?.ready || status === 'loading' || (status === 'success' && submittedBody === JSON.stringify(requestBody()))" @click="submit">
      <LoaderCircle v-if="status === 'loading'" class="spin" :size="18" /><Rocket v-else :size="18" />
      {{ status === 'loading' ? '正在检查并提交实验…' : !runtime.datasetEstimate?.ready ? '等待输入数据校验通过' : '提交到 ModelArts' }}
      </button>
    </div>
    <p v-if="error" class="error-message" role="alert">{{ error }}</p>
    <article v-if="status === 'success'" class="submit-result"><CheckCircle2 :size="25" /><div><strong>实验已受理</strong><span>后续作业按依赖关系自动提交。</span></div></article>
    <p v-if="connectionError" class="error-message" role="alert">状态服务连接失败：{{ connectionError }}。请在左侧实验作业核对提交结果，勿重复提交。</p>
  </section>
</template>
<style scoped>
.job-plan-scroll { overflow-x: auto; }
.job-plan { border-collapse: collapse; width: 100%; font-size: 13px; }
.job-plan th, .job-plan td { padding: 12px; border-bottom: 1px solid #e2e8f3; text-align: left; }
.job-plan th { background: #f1f5ff; color: #526487; }
.job-plan td { overflow-wrap: anywhere; min-width: 100px; }
.job-plan tbody tr:hover { background: #f7faff; }
.modelarts-heading { margin-top: 26px; }
.modelarts-heading h3 { margin-bottom: 0; }
.job-commands { margin-top: 28px; }
.job-commands > p, .job-command-heading small { color: var(--text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.job-command-heading { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 14px; margin-bottom: 18px; }
.job-command-heading h3 { margin-bottom: 6px; }
.job-commands textarea { width: 100%; font-family: Consolas, monospace; }
</style>
