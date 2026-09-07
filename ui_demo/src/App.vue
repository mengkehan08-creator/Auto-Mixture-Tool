<script setup>
import { reactive, ref } from 'vue'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import AppSidebar from './components/AppSidebar.vue'
import StepNavigation from './components/StepNavigation.vue'
import EvaluationConfigStep from './components/steps/EvaluationConfigStep.vue'
import MixingStrategyStep from './components/steps/MixingStrategyStep.vue'
import ReviewSubmitStep from './components/steps/ReviewSubmitStep.vue'
import TrainingConfigStep from './components/steps/TrainingConfigStep.vue'
import { createEvaluationConfig, createRuntimeConfig, createStrategy, createTrainingConfig, stepOptions } from './data/defaults'

const currentStep = ref(1)
const showingDetail = ref(false)
const strategies = reactive([createStrategy('quadmix'), createStrategy('manual'), createStrategy('random')])
const training = reactive(createTrainingConfig())
const evaluation = reactive(createEvaluationConfig())
const runtime = reactive(createRuntimeConfig())

</script>

<template>
  <div class="app-shell">
    <AppSidebar />
    <main class="main-content">
      <header class="topbar">
        <div><h1>创建配比实验</h1><p>配置算法、训练与评测后提交至 ModelArts</p></div>
        <span class="user-chip"><span>研</span>研究用户</span>
      </header>

      <StepNavigation v-if="!showingDetail" :current-step="currentStep" @change="currentStep = $event" />

      <MixingStrategyStep v-if="currentStep === 1" :strategies="strategies" :runtime="runtime" />
      <TrainingConfigStep v-else-if="currentStep === 2" :config="training" :runtime="runtime" />
      <EvaluationConfigStep v-else-if="currentStep === 3" :config="evaluation" />
      <ReviewSubmitStep v-else :strategies="strategies" :training="training" :evaluation="evaluation" :runtime="runtime" @detail-change="showingDetail = $event" />

      <footer v-if="!showingDetail" class="page-actions">
        <button v-if="currentStep > 1" class="button secondary" type="button" @click="currentStep--"><ChevronLeft :size="16" />上一步</button>
        <span v-else></span>
        <button v-if="currentStep < 4" class="button primary" type="button" @click="currentStep++">下一步：{{ stepOptions[currentStep].label }}<ChevronRight :size="16" /></button>
      </footer>
    </main>
  </div>
</template>
