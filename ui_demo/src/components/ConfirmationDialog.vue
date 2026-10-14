<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
defineProps({ title: String, message: String, confirmLabel: { type: String, default: '确认继续' } })
const emit = defineEmits(['confirm', 'cancel'])
const dialog = ref(null)
onMounted(() => dialog.value.showModal())
onBeforeUnmount(() => dialog.value?.close())
</script>
<template><dialog ref="dialog" class="confirmation-dialog" aria-labelledby="confirmation-title" @cancel.prevent="emit('cancel')">
  <h3 id="confirmation-title">{{ title }}</h3><p>{{ message }}</p><footer><button class="button secondary" type="button" autofocus @click="emit('cancel')">取消</button><button class="button primary" type="button" @click="emit('confirm')">{{ confirmLabel }}</button></footer>
</dialog></template>
<style scoped>
dialog { max-width: min(500px, calc(100vw - 32px)); border: 1px solid #dce5f4; border-radius: 18px; padding: 26px; box-shadow: 0 20px 80px #13284738; color: #23395c; }
dialog::backdrop { background: #172c505e; backdrop-filter: blur(3px); } h3 { margin: 0 0 14px; } p { line-height: 1.9; color: #5c6d88; } footer { display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px; }
</style>
