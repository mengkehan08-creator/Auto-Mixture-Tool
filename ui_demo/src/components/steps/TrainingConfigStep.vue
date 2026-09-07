<script setup>
defineProps({ config: { type: Object, required: true }, runtime: { type: Object, required: true } })
</script>

<template>
  <section class="step-panel">
    <div class="section-title-row"><div><h2>训练配置</h2><p>第二个 ModelArts 作业依次训练并评测第一个作业生成的全部采样集。</p></div></div>

    <div class="config-block">
      <h3>训练框架</h3>
      <div class="segmented"><button type="button" :class="{ active: config.frameworkSource === 'builtin' }" @click="config.frameworkSource = 'builtin'">使用内置框架</button><button type="button" :class="{ active: config.frameworkSource === 'obs' }" @click="config.frameworkSource = 'obs'">OBS 挂载框架</button></div>
      <div v-if="config.frameworkSource === 'builtin'" class="form-grid two-cols"><label class="field"><span>框架</span><select v-model="config.framework"><option>NanoChat</option></select></label></div>
      <label class="field"><span>{{ config.frameworkSource === 'builtin' ? 'NanoChat 代码 OBS 地址' : 'NanoChat 兼容框架 OBS 地址' }}</span><input v-model="config.frameworkObsUri" placeholder="obs://bucket/path/nanochat-npu/" /><small>请先上传到 OBS；当前执行适配器要求与 NanoChat 启动接口兼容。</small></label>
    </div>

    <div class="config-block">
      <h3>训练模型</h3>
      <div class="segmented"><button type="button" :class="{ active: config.modelSource === 'builtin' }" @click="config.modelSource = 'builtin'">使用内置配置</button><button type="button" :class="{ active: config.modelSource === 'obs' }" @click="config.modelSource = 'obs'">OBS 挂载模型</button></div>
      <div v-if="config.modelSource === 'builtin'" class="form-grid two-cols"><label class="field"><span>初始化方式</span><select v-model="config.model"><option>NanoChat-Base</option></select><small>从所选模型目录的 base_checkpoints/模型标签 加载初始权重；不是在线下载模型。</small></label></div>
      <div class="form-grid two-cols"><label class="field"><span>NanoChat 模型目录 OBS 地址</span><input v-model="config.modelObsUri" placeholder="obs://bucket/path/nanochat_model_dir/" /></label><label class="field"><span>基础模型标签</span><input v-model="config.baseModelTag" placeholder="d24" /></label></div>
    </div>

    <div class="config-block"><h3>训练参数</h3><div class="form-grid three-cols"><label class="field"><span>目标参数/数据比例</span><input v-model.number="config.targetParamDataRatio" type="number" min="0.01" step="0.01" /></label><label class="field"><span>每节点 NPU 数</span><input v-model.number="config.devicesPerNode" type="number" min="1" max="8" /></label><label class="field"><span>训练评测作业节点数</span><input v-model.number="config.nodes" type="number" min="1" max="16" /><small>与配比作业独立配置</small></label></div></div>

    <div class="config-block"><h3>训练步数与批量</h3><div class="form-grid two-cols">
      <label class="field"><span>训练步数</span><input v-model.number="config.numIterations" type="number" min="0" step="1" /><small>0：按数据预算自动计算；正整数：每种配比模型均使用指定步数。不会改变配比采样量。</small></label>
      <label class="field"><span>单卡批量大小</span><input v-model.number="config.deviceBatchSize" type="number" min="1" step="1" /><small>默认 1。增大会增加显存占用，需与模型和全局批量兼容。</small></label>
      <label class="field"><span>验证损失检查间隔</span><input v-model.number="config.evalEvery" type="number" min="-1" step="1" /><small>单位：训练步数。-1：关闭；正整数：每隔指定步数检查验证损失。</small></label>
      <label class="field"><span>任务评测间隔</span><input v-model.number="config.coreMetricEvery" type="number" min="-1" step="1" /><small>单位：训练步数。-1：关闭；正整数：每隔指定步数运行任务评测。与训练结束后的评测独立。</small></label>
    </div></div>
    <div class="config-block"><h3>离线运行资源</h3>
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
