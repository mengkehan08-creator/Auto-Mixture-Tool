<script setup>
import { strategyNameHint } from '../../strategy-names'
import { Code2, Library } from '@lucide/vue'
import StrategyScriptInput from './StrategyScriptInput.vue'

defineProps({ modelValue: { type: Object, required: true } })
</script>

<template>
  <div class="form-grid two-cols">
    <label class="field"><span>策略名称（可自定义）</span><input v-model="modelValue.name" :placeholder="strategyNameHint(modelValue)" /></label>
    <label class="field"><span>随机种子</span><input v-model.number="modelValue.seed" type="number" min="0" max="4294967295" step="1" /></label>
  </div>

  <section class="strategy-source">
    <div class="source-tabs" role="group" aria-label="策略来源">
      <button type="button" :class="{ active: modelValue.source === 'builtin' }" @click="modelValue.source = 'builtin'"><Library :size="17" /><span><strong>选择内置方法</strong><small>从全部候选文档中随机选取</small></span></button>
      <button type="button" :class="{ active: modelValue.source === 'script' }" @click="modelValue.source = 'script'"><Code2 :size="17" /><span><strong>使用自定义采样脚本</strong><small>填写 OBS 地址，或上传、拖拽脚本</small></span></button>
    </div>

    <div v-if="modelValue.source === 'builtin'" class="source-content">
      <label class="field"><span>内置采样方法</span><select v-model="modelValue.builtinMethod"><option value="uniform">均匀随机采样</option></select><small>更换随机采样逻辑请填写策略脚本。</small></label>
    </div>
    <div v-else class="source-content">
      <StrategyScriptInput :model-value="modelValue" />
    </div>
  </section>
</template>
