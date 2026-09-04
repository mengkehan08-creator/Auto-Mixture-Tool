<script setup>
import { Bot, Database } from '@lucide/vue'

defineProps({ config: { type: Object, required: true } })
const datasets = ['stem', 'gsm8k', 'mmlu_stem', 'arc_easy']

function toggleDataset(config, name) {
  const selected = config.dataset.names
  const index = selected.indexOf(name)
  if (index >= 0) selected.splice(index, 1)
  else selected.push(name)
}
</script>

<template>
  <section class="step-panel">
    <div class="section-title-row"><div><h2>评测配置</h2><p>评测集评测与自动评估 API 相互平行，可启用一种或同时启用。</p></div></div>

    <div class="method-grid">
      <article :class="['method-card', { enabled: config.dataset.enabled }]">
        <header><span class="method-icon"><Database :size="20" /></span><span><strong>评测集评测</strong><small>使用内置评测集或已上传的 OBS 目录</small></span><label class="switch"><input v-model="config.dataset.enabled" type="checkbox" /><span></span></label></header>
        <div v-if="config.dataset.enabled" class="method-body">
          <div class="segmented"><button type="button" :class="{ active: config.dataset.source === 'builtin' }" @click="config.dataset.source = 'builtin'">内置评测资源</button><button type="button" :class="{ active: config.dataset.source === 'obs' }" @click="config.dataset.source = 'obs'">OBS 路径</button></div>
          <span class="field-label">选择评测集</span>
          <div class="chip-list"><button v-for="name in datasets" :key="name" type="button" :class="{ active: config.dataset.names.includes(name) }" @click="toggleDataset(config, name)">{{ name }}</button></div>
          <label v-if="config.dataset.source === 'obs'" class="field"><span>评测资源 OBS 地址</span><input v-model="config.dataset.obsUri" placeholder="obs://bucket/path/eval_bundle/" /></label>
        </div>
      </article>

      <article :class="['method-card', { enabled: config.api.enabled }]">
        <header><span class="method-icon"><Bot :size="20" /></span><span><strong>自动评估工具 API</strong><small>调用外部模型或评分服务</small></span><label class="switch"><input v-model="config.api.enabled" type="checkbox" /><span></span></label></header>
        <div v-if="config.api.enabled" class="method-body">
          <p class="path-preview">展示预留：自动评测 API 的协议和鉴权尚未确定，本次提交不会调用。</p>
        </div>
      </article>
    </div>
  </section>
</template>
