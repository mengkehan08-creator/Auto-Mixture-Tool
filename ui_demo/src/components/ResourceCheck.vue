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
  if (props.kind === 'evaluation' && /^obs:\/\/[^/]+\/.+/.test(props.uri || '')) timer = setTimeout(check, 800)
}, { immediate: true })
onBeforeUnmount(() => { version++; clearTimeout(timer) })
async function check() {
  clearTimeout(timer)
  const current = ++version
  emit('checked', null)
  pending.value = true; message.value = ''; valid.value = false
  try {
    const result = await apiRequest('resources/validate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: props.kind, uri: props.uri }) })
    if (current === version) { valid.value = result.ready; message.value = result.message; emit('checked', result) }
  } catch (error) { if (current === version) message.value = error.message }
  finally { if (current === version) pending.value = false }
}
</script>
<template><div class="resource-check"><button type="button" class="button secondary" :disabled="pending || !uri" @click="check">{{ pending ? '正在校验…' : '校验数据' }}</button><p v-if="message" :class="valid ? 'success-message' : 'error-message'" role="status">{{ message }}</p><small v-else>提交前将重新校验当前地址。</small></div></template>
<style scoped>.resource-check { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 12px; } p { flex-basis: 100%; margin: 0; overflow-wrap: anywhere; } small { color: #62748e; }</style>
