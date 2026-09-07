<script setup>
import { CheckCircle2, LoaderCircle, Rocket } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { strategyOptions } from '../../data/defaults'
import { apiRequest } from '../../api'
import { fieldLabels, submissionFailed } from '../../workflow-state'

const props = defineProps({ strategies: Array, training: Object, evaluation: Object, runtime: Object })
const status = ref('idle')
const error = ref('')
const workflows = ref([])
const connectionError = ref('')
const validation = ref(null)
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
    script_obs_uri: item.source === 'script' ? item.scriptObsUri : '',
    script_config: item.scriptConfig || {},
  }))
}

function requestBody() {
  return {
    modelarts: props.runtime.modelarts,
    experiment_name: props.runtime.experimentName || null,
    input_data_obs_uri: props.runtime.inputDataObsUri,
    output_root_obs_uri: props.runtime.outputRootObsUri,
    mixing_nodes: props.runtime.mixingNodes,
    training_nodes: props.training.nodes,
    strategies: normalizedStrategies(),
    training: {
      framework: 'nanochat', model: props.training.model,
      base_model_tag: props.training.baseModelTag,
      target_param_data_ratio: props.training.targetParamDataRatio,
      devices_per_node: props.training.devicesPerNode,
      num_iterations: props.training.numIterations,
      device_batch_size: props.training.deviceBatchSize,
      eval_every: props.training.evalEvery,
      core_metric_every: props.training.coreMetricEvery,
    },
    evaluation: { datasets: props.evaluation.dataset.enabled ? props.evaluation.dataset.names : [] },
    resources: {
      code_obs_uri: props.runtime.codeObsUri,
      nanochat_repo_obs_uri: props.training.frameworkObsUri,
      nanochat_model_obs_uri: props.training.modelObsUri,
      quadmix_tokenizer_obs_uri: props.runtime.quadmixTokenizerObsUri,
      proxy_validation_obs_uri: props.runtime.proxyValidationObsUri,
      eval_bundle_obs_uri: props.evaluation.dataset.source === 'obs' ? props.evaluation.dataset.obsUri : props.runtime.evalBundleObsUri,
      python_wheels_obs_uri: props.runtime.pythonWheelsObsUri,
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

onMounted(() => { loadWorkflows(); timer = window.setInterval(loadWorkflows, 3000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <section class="step-panel">
    <div class="section-title-row"><div><h2>确认并提交</h2><p>一次实验提交两个作业；配比作业成功后，平台自动提交训练评测作业。</p></div></div>
    <h3>ModelArts 作业配置</h3>
    <p class="path-preview">以下参数替代脚本中的 REPLACE_ME，无需编辑或再次运行脚本。请使用可信的 ModelArts 创建作业 API 地址。Authorization 仅保存在本次页面及后端进程内存，不写回脚本或工作流文件；服务重启后需要重新提供。</p>
    <div class="form-grid two-cols">
      <label v-for="key in ['endpoint', 'region', 'workspace_id', 'workspace_name', 'image_url', 'image_repo_id', 'flavor_id', 'pool_id']" :key="key" class="field"><span>{{ fieldLabels[key] }}</span><input v-model="runtime.modelarts[key]" autocomplete="off" /></label>
      <label class="field"><span>Authorization</span><input v-model="runtime.modelarts.authorization" type="password" autocomplete="off" /><small>填写完整 Authorization 值。请通过受信任的 HTTPS 页面填写，不要分享或截图凭据。</small></label>
    </div>
    <div class="review-grid">
      <article><span>配比作业</span><strong>{{ strategyNames }}</strong><small>{{ runtime.mixingNodes }} 节点 · 先校验再生成全部采样集</small></article>
      <article><span>训练评测作业</span><strong>{{ training.framework }}</strong><small>{{ training.nodes }} 节点 · 依次处理全部采样集</small></article>
      <article><span>输出根目录</span><strong class="break-path">{{ runtime.outputRootObsUri }}</strong><small>按实验名称隔离 mixing / sampled / training</small></article>
    </div>

    <p class="path-preview">提交将使用管理员配置的 ModelArts 资源并产生计算费用。输入地址须为 obs:// 地址，而非 OBS 控制台网址。输出目录由您指定，系统自动创建独立实验子目录。</p>
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
