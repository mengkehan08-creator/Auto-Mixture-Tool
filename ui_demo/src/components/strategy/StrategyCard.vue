<script setup>
import { Trash2 } from '@lucide/vue'
import { strategyOptions } from '../../data/defaults'
import { strategyNameHint } from '../../strategy-names'
import ManualMixConfig from './ManualMixConfig.vue'
import QuadMixConfig from './QuadMixConfig.vue'
import RandomMixConfig from './RandomMixConfig.vue'
import { ref } from 'vue'
import ResourceGuide from '../ResourceGuide.vue'
const showGuide = ref(false)

defineProps({ strategy: { type: Object, required: true }, index: Number, removable: Boolean, datasetTokens: Number })
const emit = defineEmits(['remove', 'change-type'])
</script>

<template>
  <article class="strategy-card">
    <header class="strategy-header">
      <span class="strategy-number">{{ index + 1 }}</span>
      <select :value="strategy.type" aria-label="选择配比策略" @change="emit('change-type', $event.target.value)">
        <option v-for="option in strategyOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
      <button class="button secondary strategy-description" type="button" @click="showGuide = true">{{ strategyOptions.find(option => option.value === strategy.type)?.label }} · 策略说明</button>
      <button class="button danger" type="button" :disabled="!removable" :aria-label="`删除策略 ${strategy.name}`" :title="removable ? '删除此策略' : '至少保留一项策略'" @click="emit('remove')"><Trash2 :size="16" />删除</button>
    </header>

    <div class="strategy-job-fields form-grid" :class="strategy.type === 'quadmix' ? 'three-cols' : 'two-cols'">
      <label class="field"><span>配比作业名称（可自定义）</span><textarea rows="2" v-model="strategy.mixingJobName" :placeholder="strategyNameHint(strategy)" maxlength="64" ></textarea></label>
      <label class="field"><span>配比节点数</span><input v-model.number="strategy.mixingNodes" type="number" min="1" max="16" /></label>
      <label class="field"><span>配比任务优先级</span><select v-model.number="strategy.mixingPriority"><option :value="1">1</option><option :value="2">2</option><option :value="3">3</option></select></label>
    </div>
    <small v-if="strategy.type !== 'quadmix'">人工和随机策略目前由首节点完成采样，建议 1 节点；各策略作业可并行运行。</small>
    <QuadMixConfig v-if="strategy.type === 'quadmix'" :model-value="strategy" :dataset-tokens="datasetTokens" />
    <ManualMixConfig v-else-if="strategy.type === 'manual'" :model-value="strategy" />
    <RandomMixConfig v-else :model-value="strategy" />
    <ResourceGuide v-if="showGuide" :kind="strategy.type" @close="showGuide = false" />
  </article>
</template>
<style scoped>
.strategy-job-fields { margin-bottom: 20px; padding-bottom: 20px; border-bottom: 1px solid #e2e8f3; align-items: start; }
.strategy-job-fields .field { margin: 0; }
</style>
