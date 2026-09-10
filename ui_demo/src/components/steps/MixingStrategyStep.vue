<script setup>
import { Plus, Sparkles } from '@lucide/vue'
import { createStrategy } from '../../data/defaults'
import StrategyCard from '../strategy/StrategyCard.vue'

const props = defineProps({
  strategies: { type: Array, required: true },
  runtime: { type: Object, required: true },
})

function addStrategy() {
  props.strategies.push(createStrategy('manual'))
}

function changeType(index, type) {
  props.strategies.splice(index, 1, createStrategy(type))
}

function useRecommended() {
  props.strategies.splice(0, props.strategies.length, createStrategy('quadmix'), createStrategy('manual'), createStrategy('random'))
}
</script>

<template>
  <section class="step-panel">
    <div class="section-title-row">
      <div><h2>配比与采样配置</h2><p>每项策略创建独立配比作业，可并行运行。各自完成后自动提交对应训练作业。</p></div>
      <div class="button-row"><button class="button secondary" type="button" @click="useRecommended"><Sparkles :size="16" />推荐配置</button><button class="button primary" type="button" @click="addStrategy"><Plus :size="16" />增加配比策略</button></div>
    </div>

    <div class="config-block">
      <h3>数据与作业输出</h3>
      <div class="form-grid two-cols">
        <label class="field"><span>实验名称（可选）</span><input v-model="runtime.experimentName" placeholder="留空则按启动时间生成" /></label>
        <label class="field"><span>输入 Parquet 数据 OBS 地址</span><input v-model="runtime.inputDataObsUri" placeholder="obs://bucket/path/prepared_parquet/" /></label>
        <label class="field"><span>实验输出目录（可自定义）</span><input v-model="runtime.outputRootObsUri" placeholder="obs://bucket/path/chengchao/" /><small>可选择任意有写入权限的 OBS 桶和目录。不支持本地文件夹或控制台网页链接。</small></label>
      </div>
      <p class="path-preview">输出预览：<code>{{ runtime.outputRootObsUri.replace(/\/$/, '') }}/runs/实验名-时间-编号/strategies/策略编号/</code>，各策略独立保存配比、采样和训练日志。</p>
    </div>


    <StrategyCard
      v-for="(strategy, index) in strategies"
      :key="strategy.id"
      :strategy="strategy"
      :index="index"
      :removable="strategies.length > 1"
      @remove="strategies.splice(index, 1)"
      @change-type="changeType(index, $event)"
    />
  </section>
</template>
