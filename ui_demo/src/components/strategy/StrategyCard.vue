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

    <div class="config-block form-grid three-cols">
      <label class="field"><span>配比作业名称</span><input v-model="strategy.mixingJobName" placeholder="留空自动按时间命名" maxlength="64" /></label>
      <label class="field"><span>配比节点数</span><input v-model.number="strategy.mixingNodes" type="number" min="1" max="16" /></label>
      <label class="field"><span>配比任务优先级</span><select v-model.number="strategy.mixingPriority"><option :value="1">1</option><option :value="2">2</option><option :value="3">3</option></select></label>
    </div>
    <small v-if="strategy.type !== 'quadmix'">人工和随机策略目前由首节点完成采样，建议 1 节点；各策略作业可并行运行。</small>
    <QuadMixConfig v-if="strategy.type === 'quadmix'" :model-value="strategy" />
    <ManualMixConfig v-else-if="strategy.type === 'manual'" :model-value="strategy" />
    <RandomMixConfig v-else :model-value="strategy" />
  </article>
</template>
