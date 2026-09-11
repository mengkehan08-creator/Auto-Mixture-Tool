<script setup>
import { strategyLabel, trainingNameHint } from '../../strategy-names'
defineProps({ config: { type: Object, required: true }, runtime: { type: Object, required: true }, strategies: { type: Array, default: () => [] } })

const trainingFields = [
  { key: 'token_budget', label: '训练 Token 预算', min: 1, max: 9007199254740991, hint: '本次模型训练的 Token 总量，训练步数据此自动计算。' },
  { key: 'devices_per_node', label: '每节点 NPU 数', min: 1, max: 8, hint: '每个训练节点使用的卡数。' },
  { key: 'device_batch_size', label: '单卡批量大小', min: 1, max: 4096, hint: '每张卡一次处理的序列数，显存不足时调小。' },
  { key: 'eval_every', label: '验证损失检查间隔', min: -1, max: 2147483647, hint: '每隔多少训练步计算验证损失；-1 表示关闭。' },
  { key: 'core_metric_every', label: '任务评测间隔', min: -1, max: 2147483647, hint: '训练期间的任务评测频率；-1 表示关闭，不影响训练后的独立评测。' },
]
</script>

<template>
  <section class="step-panel">
    <div class="section-title-row"><div><h2>训练配置</h2><p>各作业独立选择框架、节点和训练参数，共用初始模型。配比成功后自动启动对应训练。</p></div></div>
    <div v-for="strategy in strategies" :key="strategy.id" class="config-block">
      <h3>{{ strategyLabel(strategy) }} · 训练作业</h3>
      <div class="job-framework">
        <div class="segmented" role="group" :aria-label="`${strategyLabel(strategy)} 训练框架来源`">
          <button type="button" :class="{ active: strategy.trainingFrameworkSource === 'builtin' }" @click="strategy.trainingFrameworkSource = 'builtin'">使用内置框架</button>
          <button type="button" :class="{ active: strategy.trainingFrameworkSource === 'obs' }" @click="strategy.trainingFrameworkSource = 'obs'">OBS 挂载框架</button>
        </div>
        <label v-if="strategy.trainingFrameworkSource === 'obs'" class="field"><span>NanoChat 兼容框架 OBS 地址</span><input v-model="strategy.trainingFrameworkObsUri" :placeholder="config.frameworkObsUri" /><small>独立挂载到本策略作业，须兼容 NanoChat 启动接口及模型格式。</small></label>
        <p v-else>内置 NanoChat · 使用下方默认代码地址</p>
      </div>
      <div class="form-grid two-cols">
        <label class="field"><span>训练作业名称（可自定义）</span><input v-model="strategy.trainingJobName" maxlength="64" :placeholder="trainingNameHint(strategy)" /></label>
        <label class="field"><span>保存模型名称</span><input v-model="strategy.modelName" maxlength="128" placeholder="留空使用策略名及实验时间" /></label>
        <label class="field"><span>训练节点数</span><input v-model.number="strategy.trainingNodes" type="number" min="1" max="16" /></label>
        <label class="field"><span>训练任务优先级</span><select v-model.number="strategy.trainingPriority"><option :value="1">1</option><option :value="2">2</option><option :value="3">3</option></select></label>
        <label v-for="field in trainingFields" :key="field.key" class="field">
          <span>{{ field.label }}</span>
          <input v-model.number="strategy.trainingOverrides[field.key]" type="number" :min="field.min" :max="field.max" :aria-describedby="`training-${strategy.id}-${field.key}`" />
          <small :id="`training-${strategy.id}-${field.key}`">{{ field.hint }}</small>
        </label>
      </div>
    </div>

    <div class="config-block">
      <h3>默认 NanoChat 框架</h3>
      <label class="field"><span>NanoChat 代码 OBS 地址</span><input v-model="config.frameworkObsUri" placeholder="obs://bucket/path/nanochat-npu/" /><small>用于选择内置框架的作业及最终汇总评测；各作业可在上方独立指定 OBS 框架。</small></label>
    </div>

    <div class="config-block">
      <h3>训练模型</h3>
      <label class="field"><span>模型输出 OBS 目录</span><input v-model="config.outputObsUri" placeholder="留空沿用实验输出目录" /><small>保存各策略训练后的模型及检查点，自动追加 runs/实验名称/，避免覆盖。</small></label>
      <div class="segmented"><button type="button" :class="{ active: config.modelSource === 'builtin' }" @click="config.modelSource = 'builtin'">使用内置配置</button><button type="button" :class="{ active: config.modelSource === 'obs' }" @click="config.modelSource = 'obs'">OBS 挂载模型</button></div>
      <div v-if="config.modelSource === 'builtin'" class="form-grid two-cols"><label class="field"><span>初始化方式</span><select v-model="config.model"><option>NanoChat-Base</option></select><small>从模型目录的 base_checkpoints/模型标签 加载初始权重。</small></label></div>
      <div class="form-grid two-cols"><label class="field"><span>NanoChat 模型目录 OBS 地址</span><input v-model="config.modelObsUri" placeholder="obs://bucket/path/nanochat_model_dir/" /></label><label class="field"><span>基础模型标签</span><input v-model="config.baseModelTag" placeholder="d24" /></label></div>
    </div>

    <div class="config-block"><h3>采样预算设置</h3><label class="field"><span>目标参数/数据比例</span><input v-model.number="config.targetParamDataRatio" type="number" min="0.01" step="0.01" /><small>用于计算采样数据规模。各模型的训练 Token 预算在上方对应作业中分别设置。</small></label></div>
    <div class="config-block"><h3>运行依赖配置</h3>
      <div v-for="(resource, index) in runtime.offlineResources" :key="index" class="resource-row">
        <label class="field"><span>name</span><input v-model="resource.name" placeholder="自定义资源名称" /></label>
        <label class="field"><span>OBS 地址</span><input v-model="resource.uri" /></label>
        <button class="resource-action resource-delete" type="button" :aria-label="`删除 ${resource.name || '未命名项'}`" @click="runtime.offlineResources.splice(index, 1)">删除</button>
      </div>
      <button class="resource-action resource-add" type="button" @click="runtime.offlineResources.push({ name: '', uri: '' })">＋ 增加</button>
    </div>
  </section>
</template>

<style scoped>
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
