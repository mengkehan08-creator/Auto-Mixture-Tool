<script setup>
import { CheckCircle2, LoaderCircle, Rocket } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { strategyOptions } from '../../data/defaults'

const props = defineProps({ strategies: Array, training: Object, evaluation: Object, runtime: Object })
const status = ref('idle')
const error = ref('')
const workflows = ref([])
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
    script_config: {},
  }))
}

function requestBody() {
  return {
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
    const response = await fetch('/api/v1/workflows')
    if (response.ok) workflows.value = await response.json()
  } catch (_) { /* UI remains editable when API is unavailable. */ }
}

async function submit() {
  status.value = 'loading'
  error.value = ''
  try {
    const response = await fetch('/api/v1/workflows', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody()),
    })
    const body = await response.json()
    if (!response.ok) throw new Error(body.detail || '提交失败')
    status.value = 'success'
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
    <div class="review-grid">
      <article><span>配比作业</span><strong>{{ strategyNames }}</strong><small>{{ runtime.mixingNodes }} 节点 · 先校验再生成全部采样集</small></article>
      <article><span>训练评测作业</span><strong>{{ training.framework }}</strong><small>{{ training.nodes }} 节点 · 依次处理全部采样集</small></article>
      <article><span>输出根目录</span><strong class="break-path">{{ runtime.outputRootObsUri }}</strong><small>按实验名称隔离 mixing / sampled / training</small></article>
    </div>

    <button class="button submit-button" type="button" :disabled="status === 'loading'" @click="submit">
      <LoaderCircle v-if="status === 'loading'" class="spin" :size="18" /><Rocket v-else :size="18" />
      {{ status === 'loading' ? '正在提交配比作业…' : '一键启动实验' }}
    </button>
    <p v-if="error" class="error-message">{{ error }}</p>
    <article v-if="status === 'success'" class="submit-result"><CheckCircle2 :size="25" /><div><strong>实验已受理</strong><span>第二个作业将在第一个成功后自动提交。</span></div></article>

    <div class="workflow-list">
      <h3>已提交实验</h3>
      <article v-for="workflow in workflows" :key="workflow.id" class="workflow-card">
        <header><div><strong>{{ workflow.name }}</strong><small>{{ workflow.id }} · {{ workflow.stage }}</small></div><b>{{ workflow.progress }}%</b></header>
        <div class="progress-track"><span :style="{ width: `${workflow.progress}%` }"></span></div>
        <div class="job-grid">
          <div v-for="job in workflow.jobs" :key="job.name"><span>{{ job.module === 'mixing' ? '配比与采样' : '训练与评测' }}</span><strong>{{ job.name }}</strong><small>{{ job.status }}<template v-if="job.id"> · {{ job.id }}</template></small></div>
        </div>
        <p v-if="workflow.message" class="error-message">{{ workflow.message }}</p>
        <div class="output-paths"><span>采样集：{{ workflow.outputs.sampled }}</span><span>训练结果：{{ workflow.outputs.training }}</span></div>
      </article>
      <p v-if="!workflows.length" class="empty-state">尚未提交实验。</p>
    </div>
  </section>
</template>
