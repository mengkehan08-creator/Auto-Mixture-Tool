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
      <div v-if="config.modelSource === 'builtin'" class="form-grid two-cols"><label class="field"><span>模型</span><select v-model="config.model"><option>NanoChat-Base</option><option>NanoChat-Mid</option></select></label></div>
      <div class="form-grid two-cols"><label class="field"><span>NanoChat 模型目录 OBS 地址</span><input v-model="config.modelObsUri" placeholder="obs://bucket/path/nanochat_model_dir/" /></label><label class="field"><span>基础模型标签</span><input v-model="config.baseModelTag" placeholder="d24" /></label></div>
    </div>

    <div class="config-block"><h3>训练参数</h3><div class="form-grid three-cols"><label class="field"><span>目标参数/数据比例</span><input v-model.number="config.targetParamDataRatio" type="number" min="0.01" step="0.01" /></label><label class="field"><span>每节点 NPU 数</span><input v-model.number="config.devicesPerNode" type="number" min="1" max="8" /></label><label class="field"><span>训练评测作业节点数</span><input v-model.number="config.nodes" type="number" min="1" max="16" /><small>与配比作业独立配置</small></label></div></div>

    <div class="config-block"><h3>离线运行资源</h3><div class="form-grid two-cols"><label class="field"><span>工具代码 OBS 地址</span><input v-model="runtime.codeObsUri" /></label><label class="field"><span>QuaDMix Tokenizer OBS 地址</span><input v-model="runtime.quadmixTokenizerObsUri" /></label><label class="field"><span>代理验证集 OBS 地址</span><input v-model="runtime.proxyValidationObsUri" /></label><label class="field"><span>内置评测资源 OBS 地址</span><input v-model="runtime.evalBundleObsUri" /></label><label class="field"><span>离线 Python wheels OBS 地址</span><input v-model="runtime.pythonWheelsObsUri" /></label></div></div>
  </section>
</template>
