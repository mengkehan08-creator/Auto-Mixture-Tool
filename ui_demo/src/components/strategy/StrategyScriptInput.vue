<script setup>
import { ref } from 'vue'
import { UploadCloud, FileCode2, Link2, X } from '@lucide/vue'

const props = defineProps({ modelValue: { type: Object, required: true } })
const error = ref('')
const dragging = ref(false)
let selection = 0

function useObs(event) {
  selection++
  props.modelValue.scriptObsUri = event.target.value
  props.modelValue.scriptInput = 'obs'
  props.modelValue.scriptUpload = null
  error.value = ''
}

function removeFile() {
  selection++
  props.modelValue.scriptUpload = null
  props.modelValue.scriptInput = 'obs'
}

async function readFiles(files) {
  const current = ++selection
  error.value = ''
  if (!files.length) return
  if (files.length !== 1) { error.value = '每项策略请选择一个 .py 文件'; return }
  const file = files[0]
  if (!file.name.toLowerCase().endsWith('.py') || file.size > 32768) {
    error.value = '请选择不超过 32 KiB 的 .py 文件；更大脚本请使用 OBS 地址'
    return
  }
  try {
    const content = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
    if (current !== selection) return
    if (!content.trim()) throw new Error('empty')
    props.modelValue.scriptUpload = { name: file.name, content }
    props.modelValue.scriptInput = 'upload'
    props.modelValue.scriptObsUri = ''
  } catch { if (current === selection) error.value = '文件为空、无法读取或不是 UTF-8 编码' }
}

function onDrop(event) {
  dragging.value = false
  readFiles(event.dataTransfer.files)
}
</script>

<template>
  <div class="script-input-card">
    <label class="field obs-field"><span><Link2 :size="15" />策略脚本 OBS 地址</span><input :value="modelValue.scriptObsUri" @input="useObs" placeholder="obs://桶名/目录/strategy.py" /></label>
    <div class="script-divider"><span>或上传脚本</span></div>
    <label class="script-drop" :class="{ dragging }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="onDrop">
      <UploadCloud :size="25" class="upload-icon" />
      <span><strong>点击上传</strong>，或将脚本拖拽到这里</span>
      <input class="file-input" type="file" accept=".py" aria-label="选择策略脚本" @change="readFiles($event.target.files); $event.target.value = ''" />
      <small>.py · UTF-8 · ≤ 32 KiB</small>
    </label>
    <div v-if="modelValue.scriptUpload && modelValue.scriptInput === 'upload'" class="script-selected"><FileCode2 :size="18" /><span>{{ modelValue.scriptUpload.name }}</span><button type="button" aria-label="移除脚本" @click="removeFile"><X :size="15" /></button></div>
    <p v-if="error" role="alert">{{ error }}</p>
    <small class="input-note">二选一，后选替换前选。仅上传不含密钥的可信脚本。</small>
  </div>
</template>

<style scoped>
.script-input-card { padding: 18px; border: 1px solid #e1e8f4; border-radius: 14px; background: #fff; }
.obs-field > span { display: flex; align-items: center; gap: 7px; }
.script-divider { display: flex; align-items: center; gap: 12px; margin: 16px 0; font-size: 12px; color: #8793a9; }
.script-divider::before, .script-divider::after { content: ''; flex: 1; height: 1px; background: #edf0f6; }
.script-drop { position: relative; display: flex; align-items: center; flex-direction: column; gap: 8px; padding: 23px 12px; border: 1px dashed #b5c5eb; border-radius: 11px; background: #f7f9ff; color: #657592; cursor: pointer; transition: background .15s, border-color .15s; text-align: center; }
.script-drop:hover, .script-drop:focus-within { background: #edf3ff; border-color: #6b8de2; }
.script-drop strong, .upload-icon { color: #5277d5; }
.file-input { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }
.script-drop.dragging { background: #e7eeff; border-color: #5477de; }
.script-selected { display: flex; align-items: center; gap: 10px; margin-top: 12px; padding: 10px 12px; background: #edf7f3; border-radius: 9px; color: #337c65; font-size: 13px; }
.script-selected span { flex: 1; overflow-wrap: anywhere; min-width: 0; }
.script-selected button { display: flex; border: 0; background: #fff; color: #718494; border-radius: 6px; padding: 5px; cursor: pointer; }
.input-note { display: block; margin-top: 12px; color: #8290a6; font-size: 12px; }
[role=alert] { color: #b42318; }
</style>
