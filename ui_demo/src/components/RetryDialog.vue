<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
const props = defineProps({ busy: Boolean })
const emit = defineEmits(['close'])
const dialog = ref(null)
onMounted(() => dialog.value.showModal())
onBeforeUnmount(() => dialog.value?.close())
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="stage-retry-dialog" aria-label="阶段重试配置" @cancel.prevent="!props.busy && emit('close')">
      <slot />
    </dialog>
  </Teleport>
</template>

<style scoped>
.stage-retry-dialog { width: min(940px, calc(100vw - 32px)); max-height: calc(100dvh - 48px); box-sizing: border-box; overflow-y: auto; border: 1px solid #dce5f4; border-radius: 18px; padding: 24px; background: #fff; color: #23395c; box-shadow: 0 20px 80px #13284738; }
.stage-retry-dialog::backdrop { background: #172c5066; }
.stage-retry-dialog :deep(.retry-panel), .stage-retry-dialog :deep(form.config-block) { margin: 0; padding: 0; border: 0; background: transparent; }
.stage-retry-dialog :deep(input), .stage-retry-dialog :deep(textarea) { min-width: 0; }
@media (max-width: 650px) { .stage-retry-dialog { padding: 16px; } .stage-retry-dialog :deep(.two-cols) { grid-template-columns: 1fr; } }
</style>
