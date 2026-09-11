<script setup>
import { strategyNameHint } from '../../strategy-names'
defineProps({ modelValue: { type: Object, required: true } })
</script>

<template>
  <div class="form-grid three-cols">
    <label class="field"><span>策略名称（可自定义）</span><input v-model="modelValue.name" :placeholder="strategyNameHint(modelValue)" /></label>
    <label class="field"><span>代理实验数</span><input v-model.number="modelValue.proxyExperiments" type="number" min="1" /><small>建议按可用设备数的倍数设置</small></label>
    <label class="field"><span>代理实验步数</span><input v-model.number="modelValue.proxySteps" type="number" min="1" /></label>
    <label class="field"><span>参数搜索次数</span><input v-model.number="modelValue.searchCount" type="number" min="1" /></label>
    <label class="field"><span>随机种子</span><input v-model.number="modelValue.seed" type="number" /></label>
    <label class="field"><span>设备类型</span><select v-model="modelValue.deviceType"><option>NPU</option></select><small>当前 ModelArts 启动模板适配 Ascend NPU。</small></label>
    <label class="field"><span>每节点设备数</span><input v-model.number="modelValue.devicesPerNode" type="number" min="1" /></label>
  </div>
</template>
