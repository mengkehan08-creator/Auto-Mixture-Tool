<script setup>
import { reactive, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import AppSidebar from './components/AppSidebar.vue'
import ConfirmationDialog from './components/ConfirmationDialog.vue'
import WorkflowJobs from './components/WorkflowJobs.vue'
import ResultAnalysis from './components/ResultAnalysis.vue'
import { copyWorkflow } from './copy-workflow'
import { syncSharedTraining } from './shared-training.js'
import StepNavigation from './components/StepNavigation.vue'
import StrategyActions from './components/StrategyActions.vue'
import EvaluationConfigStep from './components/steps/EvaluationConfigStep.vue'
import MixingStrategyStep from './components/steps/MixingStrategyStep.vue'
import ReviewSubmitStep from './components/steps/ReviewSubmitStep.vue'
import TrainingConfigStep from './components/steps/TrainingConfigStep.vue'
import { createEvaluationConfig, createRuntimeConfig, createStrategy, createTrainingConfig, stepOptions, trainingParameters } from './data/defaults'

const currentStep = ref(1)
const page = ref('create')
const selectedId = ref('')
const formVersion = ref(0)
const resetVisible = ref(false)
const copyNotice = ref('')
const navigationHistory = ref([])
function navigate(nextPage, step = currentStep.value, id = '') {
  if (page.value === nextPage && currentStep.value === step && selectedId.value === id) return
  navigationHistory.value.push({ page: page.value, step: currentStep.value, id: selectedId.value })
  page.value = nextPage
  currentStep.value = step
  selectedId.value = id
}
function goBack() {
  const previous = navigationHistory.value.pop()
  if (!previous) return
  page.value = previous.page
  currentStep.value = previous.step
  selectedId.value = previous.id
}
function openJob(id) { navigate('jobs', currentStep.value, id) }
function copyJob(config) {
  const draft = copyWorkflow(config)
  Object.assign(runtime, draft.runtime)
  Object.assign(training, draft.training)
  Object.assign(evaluation, draft.evaluation)
  strategies.splice(0, strategies.length, ...draft.strategies)
  formVersion.value++
  navigate('create', 1)
  copyNotice.value = '已复制作业配置，请调整参数并重新填写身份认证凭据。尚未提交新作业。'
}
const strategies = reactive([createStrategy('quadmix'), createStrategy('manual'), createStrategy('random')])
const training = reactive(createTrainingConfig())
const evaluation = reactive(createEvaluationConfig())
const runtime = reactive(createRuntimeConfig())
watch(() => runtime.inputDataObsUri, () => {
  runtime.datasetEstimate = null
})
// Shared defaults apply to every strategy; explicit batch node overrides survive edits.
watch(() => [trainingParameters(training), training.frameworkSource, training.frameworkObsUri, training.nodes, training.priority,
  strategies.map(s => [s.id, s.trainingNodesOverride])], () => syncSharedTraining(strategies, training), { deep: true, immediate: true })
function sidebarNavigate(destination) {
  if (destination !== 'create') return navigate(destination)
  resetVisible.value = true
}
function resetExperiment() {
  resetVisible.value = false
  for (const [target, value] of [[training, createTrainingConfig()], [evaluation, createEvaluationConfig()], [runtime, createRuntimeConfig()]]) {
    for (const key of Object.keys(target)) delete target[key]
    Object.assign(target, value)
  }
  strategies.splice(0, strategies.length, ...['quadmix', 'manual', 'random'].map(createStrategy))
  copyNotice.value = ''; formVersion.value++; navigationHistory.value = []
  page.value = 'create'; currentStep.value = 1; selectedId.value = ''
}

</script>

<template>
  <div class="app-shell">
    <AppSidebar :page="page" @navigate="sidebarNavigate" />
    <ConfirmationDialog v-if="resetVisible" title="创建新的实验？" message="将恢复全部默认设置，当前未提交的配置会被清空。已提交的实验作业不会受影响。" confirm-label="确认创建" @cancel="resetVisible = false" @confirm="resetExperiment" />
    <main class="main-content">
      <div class="workspace-header">
      <header class="topbar">
        <button class="button secondary" type="button" :disabled="!navigationHistory.length" @click="goBack" aria-label="返回上一页面"><ChevronLeft :size="16" />返回</button>
        <div><h1>{{ page === 'analysis' ? '结果分析' : page === 'jobs' ? '实验作业管理' : '创建配比实验' }}</h1><p>配置算法、训练与评测后提交至 ModelArts</p></div>
        <span class="user-chip"><span>配</span>配比用户</span>
      </header>
      <StepNavigation v-if="page === 'create'" :current-step="currentStep" @change="navigate('create', $event)" />
      <StrategyActions v-if="page === 'create' && currentStep === 1" :strategies="strategies" />
      </div>

      <WorkflowJobs v-show="page === 'jobs'" :selected-id="selectedId" @select="navigate('jobs', currentStep, $event)" @copy="copyJob" @analysis="navigate('analysis', currentStep, $event)" />
      <ResultAnalysis v-if="page === 'analysis'" :workflow-id="selectedId" @back="navigate('jobs', currentStep, selectedId)" />
      <div v-show="page === 'create'" class="creation-form">
      <p v-if="copyNotice" class="path-preview">{{ copyNotice }}</p>

      <MixingStrategyStep v-show="currentStep === 1" :key="formVersion" :strategies="strategies" :runtime="runtime" :training-nodes="training.nodes" />
      <TrainingConfigStep v-if="currentStep === 2" :config="training" :runtime="runtime" :strategies="strategies" />
      <EvaluationConfigStep v-else-if="currentStep === 3" :config="evaluation" :training="training" :runtime="runtime" :strategies="strategies" :model-output="training.outputObsUri ? `${training.outputObsUri.replace(/\/$/, '')}/runs/{实验名称}/` : `${runtime.outputRootObsUri.replace(/\/$/, '')}/runs/{实验名称}/training/checkpoints/`" />
      <ReviewSubmitStep v-else-if="currentStep === 4" :key="formVersion" :strategies="strategies" :training="training" :evaluation="evaluation" :runtime="runtime" @created="openJob" />

      <footer class="page-actions" aria-label="实验配置翻页">
        <button v-if="currentStep > 1" class="button secondary" type="button" @click="navigate('create', currentStep - 1)"><ChevronLeft :size="16" />上一步</button>
        <button v-if="currentStep < 4" class="button primary" type="button" @click="navigate('create', currentStep + 1)">下一步：{{ stepOptions[currentStep].label }}<ChevronRight :size="16" /></button>
      </footer>
      </div>
    </main>
  </div>
</template>
