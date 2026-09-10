<script setup>
import { stepOptions } from '../data/defaults'

defineProps({ currentStep: { type: Number, required: true } })
const emit = defineEmits(['change'])
</script>

<template>
  <nav class="step-nav" aria-label="实验配置步骤">
    <button
      v-for="step in stepOptions"
      :key="step.id"
      type="button"
      :class="{ active: currentStep === step.id, complete: currentStep > step.id }"
      :aria-current="currentStep === step.id ? 'step' : undefined"
      @click="emit('change', step.id)"
    >
      <span>{{ step.id }}</span>{{ step.label }}
    </button>
  </nav>
</template>
