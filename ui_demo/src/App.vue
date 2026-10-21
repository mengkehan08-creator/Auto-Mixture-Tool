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
import { draftKey, readDraft, serializeDraft, writeDraft } from './experiment-draft.js'

let draftStorage, restoredDraft, initialDraftError = '', skipNextDraftSave = false
try {
  draftStorage = typeof window === 'undefined' ? null : window.sessionStorage
  restoredDraft = readDraft(draftStorage)
} catch { initialDraftError = '无法恢复本标签页草稿，已显示默认配置。可清空草稿后重新设置。' }
const draftError = ref(initialDraftError)
const draftRestored = ref(Boolean(restoredDraft))
const draftSaved = ref(Boolean(restoredDraft))
const currentStep = ref(restoredDraft?.step || 1)
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
function clearSavedDraft() {
  try { draftStorage?.removeItem(draftKey); draftError.value = '' }
  catch { draftError.value = '无法清除本标签页草稿，请检查浏览器存储设置。' }
  draftSaved.value = false; draftRestored.value = false
}
function openJob(id) { clearSavedDraft(); navigate('jobs', currentStep.value, id) }
function copyJob(config) {
  const draft = copyWorkflow(config)
  Object.assign(runtime, draft.runtime)
  Object.assign(training, draft.training)
  Object.assign(evaluation, draft.evaluation)
  strategies.splice(0, strategies.length, ...draft.strategies)
  formVersion.value++
  draftRestored.value = false
  navigate('create', 1)
  copyNotice.value = '已复制作业配置，请调整参数并重新填写身份认证凭据。尚未提交新作业。'
}
const strategies = reactive(restoredDraft?.strategies || [createStrategy('quadmix'), createStrategy('manual'), createStrategy('random')])
const training = reactive(restoredDraft?.training || createTrainingConfig())
const evaluation = reactive(restoredDraft?.evaluation || createEvaluationConfig())
const runtime = reactive(restoredDraft?.runtime || createRuntimeConfig())
watch(() => runtime.inputDataObsUri, () => {
  runtime.datasetEstimate = null
})
// Shared defaults apply to every strategy; explicit batch node overrides survive edits.
watch(() => [trainingParameters(training), training.frameworkSource, training.frameworkObsUri, training.nodes, training.priority,
  strategies.map(s => [s.id, s.trainingNodesOverride])], () => syncSharedTraining(strategies, training), { deep: true, immediate: !restoredDraft })
watch(() => serializeDraft({ step: currentStep.value, runtime, training, evaluation, strategies }), serialized => {
  if (skipNextDraftSave) { skipNextDraftSave = false; return }
  try {
    if (!draftStorage) throw new Error('标签页存储不可用')
    writeDraft(draftStorage, serialized)
    draftSaved.value = true; draftError.value = ''
  } catch { draftError.value = '草稿未保存，当前配置仍保留在页面中；刷新前请检查浏览器存储或缩减配置。' }
}, { flush: 'post' })
function sidebarNavigate(destination) {
  navigate(destination)
}
function resetExperiment() {
  resetVisible.value = false
  clearSavedDraft(); skipNextDraftSave = true
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
    <ConfirmationDialog v-if="resetVisible" title="新建实验并清空当前配置？" message="将恢复全部默认设置，当前未提交的配置会被清空。已提交的实验作业不会受影响。" confirm-label="确认新建" @cancel="resetVisible = false" @confirm="resetExperiment" />
    <main class="main-content">
      <div class="workspace-header">
      <header class="topbar">
        <button class="button secondary" type="button" :disabled="!navigationHistory.length" @click="goBack" aria-label="返回上一页面"><ChevronLeft :size="16" />返回</button>
        <div><h1>{{ page === 'analysis' ? '结果分析' : page === 'jobs' ? '实验作业管理' : '创建配比实验' }}</h1><p>配置算法、训练与评测后提交至 ModelArts</p></div>
        <div class="topbar-actions">
          <button v-if="page === 'create'" class="button secondary" type="button" @click="resetVisible = true">新建实验</button>
          <span class="user-chip"><span>配</span>配比用户</span>
        </div>
      </header>
      <StepNavigation v-if="page === 'create'" :current-step="currentStep" @change="navigate('create', $event)" />
      <StrategyActions v-if="page === 'create' && currentStep === 1" :strategies="strategies" />
      </div>

      <WorkflowJobs v-show="page === 'jobs'" :selected-id="selectedId" @select="navigate('jobs', currentStep, $event)" @copy="copyJob" @analysis="navigate('analysis', currentStep, $event)" />
      <ResultAnalysis v-if="page === 'analysis'" :workflow-id="selectedId" @back="navigate('jobs', currentStep, selectedId)" />
      <div v-show="page === 'create'" class="creation-form">
      <p v-if="copyNotice" class="path-preview">{{ copyNotice }}</p>
      <div v-if="draftRestored || draftSaved || draftError" class="draft-notice">
        <p v-if="draftError" role="alert" class="error-message">{{ draftError }}</p>
        <p v-else role="status">{{ draftRestored ? '已恢复本标签页草稿，认证凭据需重新填写；数据与训练计划将重新校验。' : '草稿已保存到本标签页，刷新可恢复；认证凭据不会保存。' }}</p>
      </div>

      <MixingStrategyStep v-show="currentStep === 1" :key="formVersion" :strategies="strategies" :runtime="runtime" :training-nodes="training.nodes" />
      <TrainingConfigStep v-if="currentStep === 2" :config="training" :runtime="runtime" :strategies="strategies" />
      <EvaluationConfigStep v-else-if="currentStep === 3" :config="evaluation" :training="training" :runtime="runtime" :strategies="strategies" :model-output="training.outputObsUri ? `${training.outputObsUri.replace(/\/$/, '')}/runs/{实验名称}/` : `${runtime.outputRootObsUri.replace(/\/$/, '')}/runs/{实验名称}/training/checkpoints/`" />
      <ReviewSubmitStep v-else-if="currentStep === 4" :key="formVersion" :strategies="strategies" :training="training" :evaluation="evaluation" :runtime="runtime" @accepted="clearSavedDraft" @created="openJob" />

      <footer class="page-actions" aria-label="实验配置翻页">
        <button v-if="currentStep > 1" class="button secondary" type="button" @click="navigate('create', currentStep - 1)"><ChevronLeft :size="16" />上一步</button>
        <button v-if="currentStep < 4" class="button primary" type="button" @click="navigate('create', currentStep + 1)">下一步：{{ stepOptions[currentStep].label }}<ChevronRight :size="16" /></button>
      </footer>
      </div>
    </main>
  </div>
</template>

<style scoped>
.topbar-actions { display: flex; align-items: center; flex-shrink: 0; gap: 12px; }
.topbar-actions .button { white-space: nowrap; }
.draft-notice { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; padding: 12px 16px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface-soft); }
.draft-notice p { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.8; }
.draft-notice .error-message { color: #9d2438; }
@media (max-width: 640px) { .topbar-actions { margin-left: auto; } }
</style>
