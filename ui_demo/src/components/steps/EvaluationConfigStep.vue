<script setup>
import { Bot, Database } from '@lucide/vue'
import { computed } from 'vue'
import { stemTasks, normalizeEvaluationTasks } from '../../evaluation-selection.js'

const props = defineProps({ config: { type: Object, required: true }, modelOutput: String })
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
    <div class="section-title-row"><div><h2>评测配置</h2><p>默认选中全部 STEM 评测任务，可自由调整单项；自动评估 API 尚未接入。</p></div></div>
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
              <h3>新增 OBS 评测包</h3>
              <div v-for="(pack, index) in config.obsPackages" :key="index" class="config-block">
                <label class="field"><span>名称</span><input v-model="pack.name" /></label>
                <label class="field"><span>OBS 目录</span><input v-model="pack.obs_uri" placeholder="obs://bucket/evaluation-package/" /></label>
                <button type="button" class="button secondary" @click="config.obsPackages.splice(index, 1)">删除</button>
              </div>
              <button type="button" class="button secondary" @click="config.obsPackages.push({ name: '', obs_uri: '' })">增加</button>
              <small>新增包按 core.yaml 执行，运行前检查兼容性；可与上方 STEM 同时使用。</small>
            </div>
            <h3>独立评测作业</h3>
            <label class="field"><span>模型输入 OBS 地址（自动衔接训练输出）</span><input :value="modelOutput" readonly /></label>
            <div class="form-grid two-cols">
              <label class="field"><span>评测节点数</span><input v-model.number="config.nodes" type="number" min="1" max="16" /></label>
              <label class="field"><span>每节点 NPU 数</span><input v-model.number="config.devicesPerNode" type="number" min="1" max="8" /></label>
              <label class="field"><span>评测批量大小</span><input v-model.number="config.coreEvalBatchSize" type="number" min="1" /><small>默认 16，显存不足时调小。</small></label>
            </div>
            <label class="field"><span>评测与对比报告输出 OBS 目录</span><input v-model="config.outputObsUri" placeholder="留空沿用实验输出目录" /><small>自动追加 runs/实验名称/。</small></label>
          </section>
        </div>
      </article>

      <article :class="['method-card', { enabled: config.api.enabled }]">
        <header><span class="method-icon"><Bot :size="20" /></span><span><strong>自动评估</strong><small>调用外部模型或评分服务</small></span><label class="switch"><input v-model="config.api.enabled" type="checkbox" aria-label="启用自动评估" /><span></span></label></header>
        <div v-if="config.api.enabled" class="method-body">
          <p class="path-preview" role="status">暂未接入，无法执行自动评估。仅保留选择，不创建自动评估作业。</p>
        </div>
      </article>
    </div>
    <p v-if="!config.dataset.enabled && !config.api.enabled" class="path-preview" role="status">未选择评估方式，本次只运行配比和训练，不创建评测作业。</p>
  </section>
</template>

<style scoped>
.method-grid { align-items: start; }
.switch { position: relative; flex-shrink: 0; }
.switch input { display: block; position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; opacity: 0; z-index: 1; cursor: pointer; }
.switch input:focus-visible + span { outline: 2px solid #4567b9; outline-offset: 3px; }
.evaluation-job-settings { margin-top: 20px; padding-top: 18px; border-top: 1px solid #e4eaf5; }
.evaluation-job-settings h3 { margin-bottom: 16px; font-size: 14px; }
.eval-selection-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 16px 0 12px; }
.eval-selection-heading .field-label { margin: 0; }
.stem-select-all { padding: 6px 12px; border: 1px solid #d6e1f6; border-radius: 7px; background: #f4f7ff; color: #4567b9; font-size: 12px; font-weight: 600; }
.stem-select-all.active { border-color: #98b1ee; background: #eaf1ff; color: #325bc2; }
.stem-select-all:hover { background: #dfeaff; }
.eval-selection-count { display: block; margin-top: 12px; color: #7a879d; font-size: 12px; }
</style>
