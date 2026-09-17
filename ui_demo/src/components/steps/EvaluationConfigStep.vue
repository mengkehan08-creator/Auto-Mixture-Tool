<script setup>
import { Bot, Database } from '@lucide/vue'
import { computed, ref } from 'vue'
import { stemTasks, normalizeEvaluationTasks } from '../../evaluation-selection.js'
import ModelLibrary from '../ModelLibrary.vue'
import ResourceGuide from '../ResourceGuide.vue'
import ResourceCheck from '../ResourceCheck.vue'
const showGuide = ref(false)

const props = defineProps({ config: { type: Object, required: true }, modelOutput: String, training: Object, runtime: Object, strategies: Array })
const comparisonReference = computed(() => ({
  model_obs_uri: props.training.modelObsUri,
  base_model_tag: props.training.baseModelTag,
  input_data_obs_uri: props.runtime.inputDataObsUri,
  training_configs: [{
    framework: 'nanochat', model: props.training.model, base_model_tag: props.training.baseModelTag,
    target_param_data_ratio: props.training.targetParamDataRatio, devices_per_node: props.training.devicesPerNode,
    token_budget: props.training.tokenBudget, num_iterations: 0, device_batch_size: props.training.deviceBatchSize,
    eval_every: props.training.evalEvery, core_metric_every: props.training.coreMetricEvery,
  }],
}))
const selectedTasks = computed(() => normalizeEvaluationTasks(props.config.dataset.names))
const allSelected = computed(() => stemTasks.every(name => selectedTasks.value.includes(name)))

function toggleDataset(config, name) {
  const selected = normalizeEvaluationTasks(config.dataset.names)
  const index = selected.indexOf(name)
  if (index >= 0) selected.splice(index, 1)
  else selected.push(name)
  config.dataset.names = selected
}
</script>

<template>
  <section class="step-panel">
    <div class="section-title-row"><div><h2>评测配置</h2><p>选择评测任务与历史模型，全部训练成功后统一对比。默认选中全部 STEM 任务。</p></div></div>
    <div class="method-grid">
      <article :class="['method-card', { enabled: config.dataset.enabled }]">
        <header><span class="method-icon"><Database :size="20" /></span><span><strong>评测集评测</strong><small>使用内置评测集或已上传的 OBS 目录</small></span><label class="switch"><input v-model="config.dataset.enabled" type="checkbox" aria-label="启用评测集评测" /><span></span></label></header>
        <div v-if="config.dataset.enabled" class="method-body">
          <div class="segmented"><button type="button" :class="{ active: config.dataset.source === 'builtin' }" @click="config.dataset.source = 'builtin'">内置评测资源</button><button type="button" :class="{ active: config.dataset.source === 'obs' }" @click="config.dataset.source = 'obs'">OBS 路径</button></div>
          <div class="eval-selection-heading"><span class="field-label">选择评测集</span>
            <button type="button" class="stem-select-all" :class="{ active: allSelected }" :aria-pressed="allSelected" @click="config.dataset.names = normalizeEvaluationTasks([...config.dataset.names, ...stemTasks])">STEM 全选</button>
          </div>
          <div class="chip-list"><button v-for="name in stemTasks" :key="name" type="button" :aria-pressed="selectedTasks.includes(name)" :class="{ active: selectedTasks.includes(name) }" @click="toggleDataset(config, name)">{{ name }}</button></div>
          <small class="eval-selection-count" role="status">已选择 {{ selectedTasks.length }} 项评测任务</small>
          <label v-if="config.dataset.source === 'obs'" class="field"><span>评测资源 OBS 地址</span><input v-model="config.dataset.obsUri" placeholder="obs://bucket/path/eval_bundle/" /></label>
          <section class="evaluation-job-settings">
            <div v-if="config.dataset.source === 'obs'">
              <div class="section-title-row"><div><h3>OBS 评测数据</h3><small>自动识别常见格式；无法评测时说明原因</small></div><button class="button secondary" type="button" @click="showGuide = true">示例</button></div>
              <div v-for="(pack, index) in config.obsPackages" :key="index" class="config-block evaluation-package">
                <header><strong>评测包 {{ index + 1 }}</strong><button type="button" class="resource-action resource-delete" @click="config.obsPackages.splice(index, 1)">删除</button></header>
                <label class="field"><span>名称</span><input v-model="pack.name" /></label>
                <label class="field"><span>OBS 目录</span><textarea rows="2" v-model="pack.obs_uri" placeholder="obs://bucket/evaluation-package/" ></textarea></label>
                <ResourceCheck kind="evaluation" :uri="pack.obs_uri" />
              </div>
              <button type="button" class="button secondary" @click="config.obsPackages.push({ name: '', obs_uri: '' })">增加</button>
              <p class="package-note">提交前检查任务类型和数据格式，不支持或无法读取时不创建 ModelArts 作业。</p>
            </div>
            <h3>独立评测作业</h3>
            <label class="field"><span>评测作业名称</span><input v-model="config.jobName" maxlength="64" placeholder="留空自动按时间命名" /></label>
            <label class="field"><span>本次模型输出根目录（按策略分别读取）</span><input :value="modelOutput" readonly /><small>自动加载各策略子目录及下方所选历史模型，模型文件不经过本工具服务器。</small></label>
            <div class="form-grid two-cols">
              <label class="field"><span>评测节点数</span><input v-model.number="config.nodes" type="number" min="1" max="16" /></label>
              <label class="field"><span>评测任务优先级</span><select v-model.number="config.priority"><option :value="1">1</option><option :value="2">2</option><option :value="3">3</option></select></label>
              <label class="field"><span>每节点 NPU 数</span><input v-model.number="config.devicesPerNode" type="number" min="1" max="8" /></label>
              <label class="field"><span>评测批量大小</span><input v-model.number="config.coreEvalBatchSize" type="number" min="1" /><small>默认 16。批量评分遇到内存不足时自动减 2 重试，最低为 1；仍不足才停止，不跳过样本。逐题生成评测不受此批量控制。</small></label>
            </div>
            <label class="field"><span>评测与对比报告输出 OBS 目录</span><textarea rows="2" v-model="config.outputObsUri" placeholder="留空沿用实验输出目录" ></textarea><small>自动追加 runs/实验名称/。</small></label>
          </section>
          <ModelLibrary :selected="config.modelIds" :reference="comparisonReference" />
        </div>
      </article>

      <article :class="['method-card', { enabled: config.api.enabled }]">
        <header><span class="method-icon"><Bot :size="20" /></span><span><strong>自动评估</strong><small>尚未接入 · 当前不创建作业</small></span><label class="switch"><input v-model="config.api.enabled" type="checkbox" aria-label="启用自动评估" /><span></span></label></header>
        <div v-if="config.api.enabled" class="method-body">
          <p class="path-preview" role="status">暂未接入，无法执行自动评估。仅保留选择，不创建自动评估作业。</p>
        </div>
      </article>
    </div>
    <p v-if="!config.dataset.enabled && !config.api.enabled" class="path-preview" role="status">未选择评估方式，本次只运行配比和训练，不创建评测作业。</p>
    <ResourceGuide v-if="showGuide" kind="evaluation" @close="showGuide = false" />
  </section>
</template>

<style scoped>
.evaluation-package { background: linear-gradient(135deg, #f5f8ff, #fff); border: 1px solid #dce6f8; }
.evaluation-package header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.evaluation-package .field { margin-top: 14px; }
.package-note { color: #5b6b85; font-size: 12px; line-height: 1.8; }
.method-grid { align-items: start; grid-template-columns: minmax(0, 2fr) minmax(250px, 1fr); }
.switch { position: relative; flex-shrink: 0; }
.switch input { display: block; position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; opacity: 0; z-index: 1; cursor: pointer; }
.switch input:focus-visible + span { outline: 2px solid #4567b9; outline-offset: 3px; }
.evaluation-job-settings { margin-top: 20px; padding-top: 18px; border-top: 1px solid #e4eaf5; }
.evaluation-job-settings h3 { margin-bottom: 16px; font-size: 14px; }
.evaluation-job-settings > .field, .evaluation-job-settings > .form-grid { margin-bottom: 18px; }
.evaluation-job-settings .config-block .button { margin-top: 12px; }
.eval-selection-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 16px 0 12px; }
.eval-selection-heading .field-label { margin: 0; }
.stem-select-all { padding: 6px 12px; border: 1px solid #d6e1f6; border-radius: 7px; background: #f4f7ff; color: #4567b9; font-size: 12px; font-weight: 600; }
.stem-select-all.active { border-color: #98b1ee; background: #eaf1ff; color: #325bc2; }
.stem-select-all:hover { background: #dfeaff; }
.eval-selection-count { display: block; margin-top: 12px; color: #7a879d; font-size: 12px; }
@media (max-width: 1180px) {
  .method-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
