<script setup>
import { Trash2 } from '@lucide/vue'
import { strategyOptions } from '../../data/defaults'
import ManualMixConfig from './ManualMixConfig.vue'
import QuadMixConfig from './QuadMixConfig.vue'
import RandomMixConfig from './RandomMixConfig.vue'

defineProps({ strategy: { type: Object, required: true }, index: Number, removable: Boolean })
const emit = defineEmits(['remove', 'change-type'])
</script>

<template>
  <article class="strategy-card">
    <header class="strategy-header">
      <span class="strategy-number">{{ index + 1 }}</span>
      <select :value="strategy.type" aria-label="选择配比策略" @change="emit('change-type', $event.target.value)">
        <option v-for="option in strategyOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
      <span class="strategy-description">{{ strategyOptions.find((option) => option.value === strategy.type)?.description }}</span>
      <button class="button danger" type="button" :disabled="!removable" @click="emit('remove')"><Trash2 :size="16" />删除</button>
    </header>

    <QuadMixConfig v-if="strategy.type === 'quadmix'" :model-value="strategy" />
    <ManualMixConfig v-else-if="strategy.type === 'manual'" :model-value="strategy" />
    <RandomMixConfig v-else :model-value="strategy" />
  </article>
</template>
