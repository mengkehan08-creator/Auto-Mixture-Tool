<script setup>
import { ref } from 'vue'
import { Plus, Sparkles } from '@lucide/vue'
import { createStrategy, strategyOptions } from '../data/defaults'
defineProps({ strategies: { type: Array, required: true } })
const type = ref('quadmix')
</script>

<template>
  <div class="strategy-actions">
    <span>已选 {{ strategies.length }} 项策略 · 每项对应独立配比与训练作业</span>
    <div class="strategy-add-controls">
      <button class="button secondary" type="button" @click="strategies.splice(0, strategies.length, createStrategy('quadmix'), createStrategy('manual'), createStrategy('random'))"><Sparkles :size="16" aria-hidden="true" />推荐配置</button>
      <select v-model="type" aria-label="新增策略类型"><option v-for="option in strategyOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select>
      <button class="button primary" type="button" @click="strategies.push(createStrategy(type))"><Plus :size="16" aria-hidden="true" />增加配比策略</button>
    </div>
  </div>
</template>

<style scoped>
.strategy-actions { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; padding: 14px 16px 2px; }
.strategy-actions > span { color: #596a82; font-size: 13px; }
.strategy-add-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.strategy-add-controls select { padding: 9px 12px; border: 1px solid #d4dff1; border-radius: 8px; background: #fff; color: #243957; }
</style>
