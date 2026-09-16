<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { apiRequest } from '../api'
const props = defineProps({ kind: String, uri: String })
const emit = defineEmits(['checked'])
const pending = ref(false), message = ref(''), valid = ref(false)
let version = 0, timer = null
watch(() => props.uri, () => {
  version++; message.value = ''; valid.value = false; pending.value = false; emit('checked', null)
  clearTimeout(timer)
  if (/^obs:\/\/[^/]+\/.+/.test(props.uri || '')) timer = setTimeout(() => check(false), 800)
}, { immediate: true })
onBeforeUnmount(() => { version++; clearTimeout(timer) })
async function check(force = true) {
  clearTimeout(timer)
  const current = ++version
  emit('checked', null)
  pending.value = true; message.value = ''; valid.value = false
  try {
    const result = await apiRequest('resources/validate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: props.kind, uri: props.uri, force }) })
    accept(result, current)
  } catch (error) { if (current === version) { message.value = error.message; pending.value = false } }
}
function accept(result, current) {
  if (current !== version) return
  valid.value = result.ready; message.value = result.message; emit('checked', result)
  pending.value = result.status === 'RUNNING'
  if (pending.value) timer = setTimeout(() => poll(result.check_id, current), 1000)
}
async function poll(id, current) {
  if (current !== version) return
  try { accept(await apiRequest(`resources/checks/${encodeURIComponent(id)}`), current) }
  catch (error) { if (current === version) { message.value = error.message; pending.value = false; emit('checked', null) } }
}
</script>
<template><div class="resource-check"><button type="button" class="button secondary" :disabled="pending || !uri" @click="check(true)">{{ pending ? '正在校验…' : '重新校验' }}</button><p v-if="message" :class="valid ? 'success-message' : pending ? '' : 'error-message'" role="status">{{ message }}</p><small v-else>填写 OBS 地址后自动校验。{{ kind === 'dataset' ? '每个文件随机抽查 3 条，提交时不再读取输入数据。' : '' }}</small></div></template>
<style scoped>.resource-check { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 12px; } p { flex-basis: 100%; margin: 0; overflow-wrap: anywhere; } small { color: #62748e; }</style>
