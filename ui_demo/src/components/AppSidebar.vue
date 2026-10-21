<script setup>
import { Boxes, FileSliders, Network, Plus, Settings2 } from '@lucide/vue'
defineProps({ page: String })
defineEmits(['navigate'])
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <span class="brand-mark" role="img" aria-label="多节点版本" title="多节点版本"><Network :size="22" aria-hidden="true" /></span>
      <span><strong>Auto Mixture</strong><small>数据配比实验工具</small></span>
    </div>

    <nav class="sidebar-nav" aria-label="主导航">
      <button :class="{ active: page === 'create' }" type="button" @click="$emit('navigate', 'create')"><Plus :size="17" />创建实验</button>
      <button :class="{ active: page === 'jobs' || page === 'analysis' }" type="button" @click="$emit('navigate', 'jobs')"><Boxes :size="17" />实验作业</button>
      <button type="button" disabled><Boxes :size="17" />组件目录（未开放）</button>
      <button type="button" disabled><FileSliders :size="17" />配置模板（未开放）</button>
    </nav>

    <div class="environment-card">
      <span><Settings2 :size="15" />运行环境</span>
      <strong>ModelArts · 以服务端配置为准</strong>
    </div>
  </aside>
</template>
