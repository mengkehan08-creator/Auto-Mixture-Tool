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
function openJob(id) { selectedId.value = id; page.value = 'jobs' }
function copyJob(config) {
  const draft = copyWorkflow(config)
  Object.assign(runtime, draft.runtime)
  Object.assign(training, draft.training)
  Object.assign(evaluation, draft.evaluation)
  strategies.splice(0, strategies.length, ...draft.strategies)
  formVersion.value++
  currentStep.value = 1
  page.value = 'create'
  copyNotice.value = '已复制作业配置，请调整参数并重新填写身份认证凭据。尚未提交新作业。'
}
const strategies = reactive([createStrategy('quadmix'), createStrategy('manual'), createStrategy('random')])
const training = reactive(createTrainingConfig())
const evaluation = reactive(createEvaluationConfig())
const runtime = reactive(createRuntimeConfig())

</script>

<template>
  <div class="app-shell">
    <AppSidebar :page="page" @navigate="page = $event; selectedId = ''" />
    <main class="main-content">
      <header class="topbar">
        <div><h1>{{ page === 'jobs' ? '实验作业管理' : '创建配比实验' }}</h1><p>配置算法、训练与评测后提交至 ModelArts</p></div>
        <span class="user-chip"><span>研</span>研究用户</span>
      </header>

      <WorkflowJobs v-if="page === 'jobs'" :selected-id="selectedId" @select="selectedId = $event" @copy="copyJob" />
      <div v-show="page === 'create'">
      <p v-if="copyNotice" class="path-preview">{{ copyNotice }}</p>
      <StepNavigation :current-step="currentStep" @change="currentStep = $event" />

      <MixingStrategyStep v-if="currentStep === 1" :strategies="strategies" :runtime="runtime" />
      <TrainingConfigStep v-else-if="currentStep === 2" :config="training" :runtime="runtime" />
      <EvaluationConfigStep v-else-if="currentStep === 3" :config="evaluation" />
      <ReviewSubmitStep v-else :key="formVersion" :strategies="strategies" :training="training" :evaluation="evaluation" :runtime="runtime" @created="openJob" />

      <footer class="page-actions">
        <button v-if="currentStep > 1" class="button secondary" type="button" @click="currentStep--"><ChevronLeft :size="16" />上一步</button>
        <span v-else></span>
        <button v-if="currentStep < 4" class="button primary" type="button" @click="currentStep++">下一步：{{ stepOptions[currentStep].label }}<ChevronRight :size="16" /></button>
      </footer>
      </div>
    </main>
  </div>
</template>
