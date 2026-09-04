<script setup>
import { Code2, Library } from '@lucide/vue'

defineProps({ modelValue: { type: Object, required: true } })
</script>

<template>
  <div class="form-grid two-cols">
    <label class="field"><span>策略名称</span><input v-model="modelValue.name" /></label>
    <label class="field"><span>随机种子</span><input v-model.number="modelValue.seed" type="number" /></label>
  </div>

  <section class="strategy-source">
    <div class="source-tabs" role="group" aria-label="策略来源">
      <button type="button" :class="{ active: modelValue.source === 'builtin' }" @click="modelValue.source = 'builtin'"><Library :size="17" /><span><strong>选择内置方法</strong><small>使用平台已提供的随机采样方式</small></span></button>
      <button type="button" :class="{ active: modelValue.source === 'script' }" @click="modelValue.source = 'script'"><Code2 :size="17" /><span><strong>上传完整策略脚本</strong><small>脚本独立定义采样、配比及执行逻辑</small></span></button>
    </div>

    <div v-if="modelValue.source === 'builtin'" class="source-content">
      <label class="field"><span>内置采样方法</span><select v-model="modelValue.builtinMethod"><option value="uniform">均匀随机采样</option></select><small>更换随机采样逻辑请填写策略脚本。</small></label>
    </div>
    <div v-else class="source-content">
      <label class="field"><span>策略脚本 OBS 地址</span><input v-model="modelValue.scriptObsUri" placeholder="obs://bucket/path/random_strategy.py" /><small>请先上传可信的 .py 脚本，平台仅传递 OBS 路径。</small></label>
      <div class="script-notice"><Code2 :size="17" /><span><strong>脚本完整接管本策略</strong><small>脚本中的采样、配比和执行逻辑将在任务中直接运行。</small></span></div>
    </div>
  </section>
</template>
