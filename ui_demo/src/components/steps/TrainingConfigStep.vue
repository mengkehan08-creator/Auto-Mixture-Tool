<script setup>
import { computed } from 'vue'
import { strategyLabel } from '../../strategy-names'
import SamplingRiskSummary from '../SamplingRiskSummary.vue'
const props = defineProps({ config: { type: Object, required: true }, runtime: { type: Object, required: true }, strategies: { type: Array, default: () => [] } })
const nodeOverrides = computed(() => props.strategies.filter(s => s.trainingNodesOverride != null))

</script>

<template>
  <section class="step-panel">
    <div class="section-title-row"><div><h2>训练配置</h2><p>统一设置训练参数、默认节点数和优先级；批量策略可单独覆盖节点数，作业与模型名称自动生成。</p></div></div>
    <div class="config-block">
      <h3>统一训练参数</h3>
      <div class="job-framework">
        <div class="segmented" role="group" aria-label="训练框架来源">
          <button type="button" :class="{ active: config.frameworkSource === 'builtin' }" @click="config.frameworkSource = 'builtin'">使用内置框架</button>
          <button type="button" :class="{ active: config.frameworkSource === 'obs' }" @click="config.frameworkSource = 'obs'">OBS 挂载框架</button>
        </div>
        <label class="field"><span>NanoChat 兼容框架 OBS 地址</span><textarea rows="2" v-model="config.frameworkObsUri" ></textarea><small>用于全部策略及最终评测，需兼容现有 NanoChat 模型与启动接口。</small></label>
      </div>
      <div class="form-grid two-cols">
        <label class="field"><span>训练 Token 预算</span><input v-model.number="config.tokenBudget" type="number" min="1" /><small>各策略使用同一预算，训练步数自动计算。</small></label>
        <label class="field"><span>每节点 NPU 数</span><input v-model.number="config.devicesPerNode" type="number" min="1" max="8" /></label>
        <label class="field"><span>默认训练节点数</span><input v-model.number="config.nodes" type="number" min="1" max="16" step="1" /><small>应用到未单独设置节点数的策略。</small></label>
        <label class="field"><span>训练任务优先级</span><select v-model.number="config.priority"><option :value="1">1</option><option :value="2">2</option><option :value="3">3</option></select><small>本次全部训练作业统一使用。</small></label>
      </div>
      <p class="training-name-note">训练作业与模型按策略参数和提交时间自动命名，具体名称规则可在任务配置中查看。</p>
      <details v-if="nodeOverrides.length" class="node-overrides"><summary>{{ nodeOverrides.length }} 项策略使用单独节点数，不随默认值变化</summary><ul><li v-for="strategy in nodeOverrides" :key="strategy.id"><span>{{ strategyLabel(strategy) }} · {{ strategy.trainingNodesOverride }} 节点</span><button type="button" class="button secondary" @click="strategy.trainingNodesOverride = null">恢复统一值</button></li></ul></details>
      <SamplingRiskSummary :strategies="strategies" :budget="config.tokenBudget" :dataset-tokens="runtime.datasetEstimate?.estimated_tokens" />
    </div>

    <div class="config-block">
      <h3>训练模型</h3>
      <label class="field"><span>模型输出 OBS 目录</span><textarea rows="2" v-model="config.outputObsUri" placeholder="留空沿用实验输出目录" ></textarea><small>保存各策略训练后的模型及检查点，自动追加 runs/实验名称/，避免覆盖。</small></label>
      <div class="segmented"><button type="button" :class="{ active: config.modelSource === 'builtin' }" @click="config.modelSource = 'builtin'">使用内置配置</button><button type="button" :class="{ active: config.modelSource === 'obs' }" @click="config.modelSource = 'obs'">OBS 挂载模型</button></div>
      <div v-if="config.modelSource === 'builtin'" class="form-grid two-cols"><label class="field"><span>初始化方式</span><select v-model="config.model"><option>NanoChat-Base</option></select><small>从模型目录的 base_checkpoints/模型标签 加载初始权重。</small></label></div>
      <div class="form-grid two-cols"><label class="field"><span>NanoChat 模型目录 OBS 地址</span><textarea rows="2" v-model="config.modelObsUri" placeholder="obs://bucket/path/nanochat_model_dir/" ></textarea></label><label class="field"><span>基础模型标签</span><input v-model="config.baseModelTag" placeholder="d24" /></label></div>
    </div>

    <div class="config-block"><h3>采样预算设置</h3><label class="field"><span>目标参数/数据比例</span><input v-model.number="config.targetParamDataRatio" type="number" min="0.01" step="0.01" /><small>用于采样数据规模设置，不保证 QuaDMix 子集能达到训练预算。</small></label></div>
    <div class="config-block"><h3>运行依赖配置</h3>
      <div v-for="(resource, index) in runtime.offlineResources" :key="index" class="resource-row">
        <label class="field"><span>name</span><input v-model="resource.name" placeholder="自定义资源名称" /></label>
        <label class="field"><span>OBS 地址</span><textarea rows="2" v-model="resource.uri" ></textarea></label>
        <button class="resource-action resource-delete" type="button" :aria-label="`删除 ${resource.name || '未命名项'}`" @click="runtime.offlineResources.splice(index, 1)">删除</button>
      </div>
      <button class="resource-action resource-add" type="button" @click="runtime.offlineResources.push({ name: '', uri: '' })">＋ 增加</button>
    </div>
  </section>
</template>

<style scoped>
.training-name-note { margin: 14px 0 0; color: #6a7e9a; font-size: 12px; } .node-overrides { margin-top: 14px; padding: 12px 16px; background: #f2f6ff; border-radius: 10px; color: #49689b; font-size: 13px; } .node-overrides summary { cursor: pointer; } .node-overrides ul { padding: 0; list-style: none; max-height: 260px; overflow: auto; } .node-overrides li { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; } .node-overrides .button { padding: 6px 10px; font-size: 12px; flex-shrink: 0; }
.job-framework { margin: 0 0 20px; padding: 16px; background: #f6f8ff; border: 1px solid #e1e8f4; border-radius: 12px; }
.job-framework p { margin: 10px 0 0; color: #657592; font-size: 13px; }
.job-framework .segmented { flex-wrap: wrap; }
.resource-row {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) minmax(0, 2.4fr) auto;
  align-items: end;
  gap: 12px;
  padding: 14px;
  margin-bottom: 12px;
  border: 1px solid #e5eaf5;
  border-radius: 10px;
  background: #f8faff;
}
.resource-row .field { min-width: 0; margin: 0; }
.resource-action {
  min-height: 34px;
  padding: 7px 14px;
  border: 1px solid transparent;
  border-radius: 7px;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: background .15s, border-color .15s;
}
.resource-delete { color: #a33b48; background: #fff0f2; border-color: #f3d8dd; margin-bottom: 3px; }
.resource-delete:hover { background: #ffe3e8; border-color: #e8b7c1; }
.resource-add { color: #355bb6; background: #edf3ff; border-color: #d4e0fa; }
.resource-add:hover { background: #dfeaff; border-color: #b3c9f5; }
.resource-action:focus-visible { outline: 2px solid #5379dc; outline-offset: 3px; }
@media (max-width: 640px) {
  .resource-row { grid-template-columns: minmax(0, 1fr) auto; }
  .resource-row .field { grid-column: 1 / -1; }
  .resource-delete { grid-column: 2; margin-bottom: 0; }
}
</style>
