<script setup>
import { ref, computed, onMounted } from 'vue'
import { apiRequest } from '../api'
import { retryDraft, retryBody } from '../stage-retry'
import { stemTasks } from '../evaluation-selection'

const props = defineProps({ workflow: Object, stage: String })
const emit = defineEmits(['close', 'created'])
const draft = ref(null)
const defaults = ref(null)
const error = ref('')
const submitting = ref(false)
const title = computed(() => props.stage === 'training' ? '训练阶段重试' : '评测阶段重试')
const input = computed(() => props.stage === 'training' ? props.workflow.outputs.sampled : props.workflow.outputs.models)
const stages = computed(() => props.stage === 'evaluation' ? ['evaluation'] :
  ['training', ...(draft.value?.evaluation.datasets.length || draft.value?.evaluation.obs_packages.length ? ['evaluation'] : [])])
const labels = { training: '训练', evaluation: '评测' }
const resources = computed(() => [
  ['code_obs_uri', '工具代码 OBS 地址'], ['nanochat_repo_obs_uri', 'NanoChat 代码 OBS 地址'],
  ['python_wheels_obs_uri', '安装包 OBS 地址'], ['eval_bundle_obs_uri', '内置评测资源 OBS 地址'],
  ...(props.stage === 'training' ? [['nanochat_model_obs_uri', '初始模型 OBS 地址']] : []),
])
let requestId = ''
let fingerprint = ''
async function load() {
  try {
    const [config, settings] = await Promise.all([
      apiRequest(`workflows/${props.workflow.id}/configuration`), apiRequest('workflow-defaults'),
    ])
    defaults.value = settings
    draft.value = retryDraft(config, settings, props.workflow, props.stage)
  } catch (reason) { error.value = reason.message }
}
async function submit() {
  if (submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    const body = retryBody(JSON.parse(JSON.stringify(draft.value)))
    const next = JSON.stringify(body)
    if (next !== fingerprint) {
      requestId = window.crypto?.randomUUID?.() || `retry_${Date.now()}_${Math.random().toString(36).slice(2)}`
      fingerprint = next
    }
    const result = await apiRequest('workflows', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, request_id: requestId }),
    })
    emit('created', result.id)
  } catch (reason) { error.value = reason.message }
  finally { submitting.value = false }
}
onMounted(load)
</script>

<template>
  <section class="retry-panel" aria-labelledby="retry-title">
    <div class="section-title-row"><h3 id="retry-title">{{ title }}</h3><button class="button secondary" type="button" :disabled="submitting" @click="emit('close')">取消重试</button></div>
    <p>直接复用前序成功输出，不再执行已完成阶段。</p>
    <div class="path-preview"><strong>{{ stage === 'training' ? '采样集输入' : '模型输入' }}</strong><div class="retry-path">{{ input }}</div></div>
    <p v-if="error" class="error-message" role="alert">{{ error }}</p>
    <p v-if="!draft">{{ error ? '配置加载失败。请关闭后重试。' : '正在读取原作业配置…' }}</p>
    <form v-else @submit.prevent="submit">
      <fieldset :disabled="submitting">
        <div v-if="stage === 'training'" class="config-block">
          <h3>训练参数</h3>
          <div class="form-grid two-cols">
            <label class="field"><span>训练节点数</span><input v-model.number="draft.training_nodes" type="number" min="1" max="16" required /></label>
            <label class="field"><span>每节点设备数</span><input v-model.number="draft.training.devices_per_node" type="number" min="1" max="8" required /></label>
            <label class="field"><span>训练 Token 预算</span><input v-model.number="draft.training.token_budget" type="number" min="1" step="1" placeholder="留空沿用采样统计预算" @input="draft.training.num_iterations = 0" /></label>
            <label class="field"><span>训练批量大小（每设备）</span><input v-model.number="draft.training.device_batch_size" type="number" min="1" required /></label>
            <label class="field"><span>训练中验证间隔</span><input v-model.number="draft.training.eval_every" type="number" min="-1" required /></label>
            <label class="field"><span>训练中基准评测间隔</span><input v-model.number="draft.training.core_metric_every" type="number" min="-1" required /></label>
            <label class="field"><span>初始模型标签</span><input v-model="draft.training.base_model_tag" required /></label>
            <label class="field"><span>模型输出 OBS 目录</span><input v-model="draft.training.output_obs_uri" placeholder="留空沿用输出根目录" /></label>
          </div>
        </div>
        <div class="config-block">
          <h3>{{ stage === 'training' ? '后续评测参数' : '评测参数' }}</h3>
          <div class="form-grid two-cols">
            <label class="field"><span>评测节点数</span><input v-model.number="draft.evaluation_nodes" type="number" min="1" max="16" required /></label>
            <label class="field"><span>每节点设备数</span><input v-model.number="draft.evaluation.devices_per_node" type="number" min="1" max="8" required /></label>
            <label class="field"><span>评测批量大小</span><input v-model.number="draft.evaluation.core_eval_batch_size" type="number" min="1" required /></label>
            <label class="field"><span>报告输出 OBS 目录</span><input v-model="draft.evaluation.output_obs_uri" placeholder="留空沿用输出根目录" /></label>
          </div>
          <div class="retry-tasks"><label v-for="task in [...new Set([...stemTasks, 'mmlu_zeroshot', ...draft.evaluation.datasets])]" :key="task"><input v-model="draft.evaluation.datasets" type="checkbox" :value="task" />{{ task }}</label></div>
          <p v-if="stage === 'training'">取消全部评测任务并移除评测包时，仅重新训练。</p>
          <div v-for="(item, index) in draft.evaluation.obs_packages" :key="index" class="form-grid two-cols">
            <label class="field"><span>评测包名称</span><input v-model="item.name" required /></label>
            <label class="field"><span>评测包 OBS 地址</span><input v-model="item.obs_uri" required /></label>
            <button class="button secondary" type="button" @click="draft.evaluation.obs_packages.splice(index, 1)">删除</button>
          </div>
          <button class="button secondary" type="button" @click="draft.evaluation.obs_packages.push({ name: '', obs_uri: '' })">增加评测包</button>
        </div>
        <details class="config-block">
          <summary>运行资源与任务配置（可修改镜像、代码和启动命令）</summary>
          <div class="form-grid two-cols">
            <label v-for="[key, label] in resources" :key="key" class="field"><span>{{ label }}</span><input v-model="draft.resources[key]" required /></label>
            <label class="field"><span>输出根目录</span><input v-model="draft.output_root_obs_uri" required /></label>
            <label class="field"><span>priority</span><select v-model.number="draft.priority"><option :value="1">1</option><option :value="2">2</option><option :value="3">3</option></select></label>
            <label v-for="key in ['endpoint', 'region', 'workspace_id', 'workspace_name', 'image_url', 'image_repo_id', 'flavor_id', 'pool_id']" :key="key" class="field"><span>{{ key }}</span><input v-model="draft.modelarts[key]" /></label>
          </div>
          <label v-for="item in stages" :key="item" class="field"><span>command（{{ labels[item] }}）</span><textarea v-model="draft.commands[item]" rows="8" required spellcheck="false"></textarea></label>
          <button class="button secondary" type="button" @click="draft.commands = { ...defaults.commands }">恢复当前默认命令</button>
        </details>
        <label v-if="defaults.auth_mode !== 'iam'" class="field"><span>Authorization</span><input v-model="draft.modelarts.authorization" type="password" autocomplete="off" placeholder="填写本次提交使用的凭据" /></label>
        <p v-else>Authorization：提交时自动获取。</p>
        <p>本次提交 {{ stages.length }} 个 ModelArts 作业：{{ stages.map(item => labels[item]).join(' → ') }}。新输出自动隔离到重试实验目录，原结果保留。</p>
        <button class="button primary" type="submit">{{ submitting ? '正在提交…' : '提交阶段重试' }}</button>
      </fieldset>
    </form>
  </section>
</template>

<style scoped>
.retry-panel { margin-top: 20px; padding: 24px; background: #f6f8ff; border: 1px solid #dce4fc; border-radius: 16px; }
fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.retry-path { overflow-wrap: anywhere; margin-top: 8px; }
.retry-tasks { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
.retry-tasks label { display: flex; gap: 6px; align-items: center; }
summary { cursor: pointer; font-weight: 600; margin-bottom: 16px; }
textarea { width: 100%; font-family: monospace; }
</style>
