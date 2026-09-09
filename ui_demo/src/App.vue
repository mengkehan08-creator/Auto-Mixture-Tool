<script setup>
import { reactive, ref } from 'vue'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import AppSidebar from './components/AppSidebar.vue'
import WorkflowJobs from './components/WorkflowJobs.vue'
import { copyWorkflow } from './copy-workflow'
import StepNavigation from './components/StepNavigation.vue'
import EvaluationConfigStep from './components/steps/EvaluationConfigStep.vue'
import MixingStrategyStep from './components/steps/MixingStrategyStep.vue'
import ReviewSubmitStep from './components/steps/ReviewSubmitStep.vue'
import TrainingConfigStep from './components/steps/TrainingConfigStep.vue'
import { createEvaluationConfig, createRuntimeConfig, createStrategy, createTrainingConfig, stepOptions } from './data/defaults'

const currentStep = ref(1)
const page = ref('create')
const selectedId = ref('')
const formVersion = ref(0)
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
  runtime.reuse = null
  runtime.reuseInput = ''
  const draft = copyWorkflow(config)
  Object.assign(runtime, draft.runtime)
  Object.assign(training, draft.training)
  Object.assign(evaluation, draft.evaluation)
  strategies.splice(0, strategies.length, ...draft.strategies)
  formVersion.value++
  navigate('create', 1)
  copyNotice.value = '已复制作业配置，请调整参数并重新填写身份认证凭据。尚未提交新作业。'
}
function restartJob({ config, workflow, stage }) {
  copyJob(config)
  runtime.reuse = { workflow_id: workflow.id, stage }
  runtime.reuseInput = stage === 'training' ? workflow.outputs.sampled : workflow.outputs.models
  runtime.commands = null
  currentStep.value = stage === 'training' ? 2 : 3
  copyNotice.value = `从${stage === 'training' ? '训练' : '评测'}重新执行：复用前序输出，已完成阶段不可修改；提交后创建新记录，不覆盖原实验。请确认新代码已更新到 OBS，并检查启动命令。`
}
const strategies = reactive([createStrategy('quadmix'), createStrategy('manual'), createStrategy('random')])
const training = reactive(createTrainingConfig())
const evaluation = reactive(createEvaluationConfig())
const runtime = reactive(createRuntimeConfig())

</script>

<template>
  <div class="app-shell">
    <AppSidebar :page="page" @navigate="navigate($event)" />
    <main class="main-content">
      <header class="topbar">
        <button class="button secondary" type="button" :disabled="!navigationHistory.length" @click="goBack" aria-label="返回上一页面"><ChevronLeft :size="16" />返回</button>
        <div><h1>{{ page === 'jobs' ? '实验作业管理' : '创建配比实验' }}</h1><p>配置算法、训练与评测后提交至 ModelArts</p></div>
        <span class="user-chip"><span>配</span>配比用户</span>
      </header>

      <WorkflowJobs v-show="page === 'jobs'" :selected-id="selectedId" @select="navigate('jobs', currentStep, $event)" @copy="copyJob" @restart="restartJob" />
      <div v-show="page === 'create'">
      <p v-if="copyNotice" class="path-preview">{{ copyNotice }}</p>
      <p v-if="runtime.reuse" class="path-preview">{{ runtime.reuse.stage === 'training' ? '采样集输入' : '模型输入' }}：{{ runtime.reuseInput }}</p>
      <StepNavigation :current-step="currentStep" @change="navigate('create', $event)" />

      <p v-if="runtime.reuse && (currentStep === 1 || (currentStep === 2 && runtime.reuse.stage === 'evaluation'))" class="path-preview">此阶段已完成，本次直接复用其输出。如需调整，请使用“复制并调整参数”新建完整实验。</p>
      <MixingStrategyStep v-else-if="currentStep === 1" :strategies="strategies" :runtime="runtime" />
      <TrainingConfigStep v-else-if="currentStep === 2" :config="training" :runtime="runtime" />
      <EvaluationConfigStep v-else-if="currentStep === 3" :config="evaluation" :model-output="runtime.reuse?.stage === 'evaluation' ? runtime.reuseInput : training.outputObsUri ? `${training.outputObsUri.replace(/\/$/, '')}/runs/{实验名称}/` : `${runtime.outputRootObsUri.replace(/\/$/, '')}/runs/{实验名称}/training/checkpoints/`" />
      <ReviewSubmitStep v-else :key="formVersion" :strategies="strategies" :training="training" :evaluation="evaluation" :runtime="runtime" @created="openJob" />

      <footer class="page-actions">
        <button v-if="currentStep > 1" class="button secondary" type="button" @click="navigate('create', currentStep - 1)"><ChevronLeft :size="16" />上一步</button>
        <span v-else></span>
        <button v-if="currentStep < 4" class="button primary" type="button" @click="navigate('create', currentStep + 1)">下一步：{{ stepOptions[currentStep].label }}<ChevronRight :size="16" /></button>
      </footer>
      </div>
    </main>
  </div>
</template>
