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
      <button type="button" :class="{ active: modelValue.source === 'builtin' }" @click="modelValue.source = 'builtin'"><Library :size="17" /><span><strong>选择内置方法</strong><small>使用平台已提供的采样方式</small></span></button>
      <button type="button" :class="{ active: modelValue.source === 'script' }" @click="modelValue.source = 'script'"><Code2 :size="17" /><span><strong>上传完整策略脚本</strong><small>脚本独立定义采样、配比及执行逻辑</small></span></button>
    </div>

    <div v-if="modelValue.source === 'builtin'" class="source-content">
      <label class="field"><span>内置采样方法</span><select v-model="modelValue.builtinMethod"><option value="default_manual">默认人工比例采样</option></select><small>通过下方领域比例控制内置方法；更换逻辑请填写策略脚本。</small></label>
    </div>
    <div v-else class="source-content">
      <label class="field"><span>策略脚本 OBS 地址</span><input v-model="modelValue.scriptObsUri" placeholder="obs://bucket/path/manual_strategy.py" /><small>请先上传可信的 .py 脚本，平台仅传递 OBS 路径。</small></label>
      <div class="script-notice"><Code2 :size="17" /><span><strong>脚本完整接管本策略</strong><small>脚本中的采样、配比和执行逻辑将在任务中直接运行。</small></span></div>
    </div>
    <div class="source-content"><label class="field"><span>领域比例</span><input :value="Object.entries(modelValue.ratios).map(([k,v]) => `${k}=${v}`).join(', ')" @change="modelValue.ratios = Object.fromEntries($event.target.value.split(',').map(x => x.trim().split('=').map((v,i) => i ? Number(v) : v)))" /><small>格式：数学=0.6, 物理=0.15, 化学=0.125, 生物学=0.125</small></label></div>
  </section>
</template>
