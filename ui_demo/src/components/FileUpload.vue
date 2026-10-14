<script setup>
import { Upload } from '@lucide/vue'

defineProps({ label: String, value: String, hint: String, accept: String })
const emit = defineEmits(['change'])

function handleFile(event) {
  emit('change', event.target.files?.[0]?.name || '')
}
</script>

<template>
  <label class="field file-field">
    <span>{{ label }}</span>
    <span class="file-control">
      <Upload :size="16" />{{ value || '选择文件' }}
      <input type="file" :accept="accept" @change="handleFile" />
    </span>
    <small>{{ value ? `已选择：${value}` : hint }}</small>
  </label>
</template>
