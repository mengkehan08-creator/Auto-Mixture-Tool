<script setup>
import { computed } from 'vue'
import { hasProgress, stageIndex, workflowStages } from '../workflow-state'
const props = defineProps({ workflow: { type: Object, required: true } })
const current = computed(() => stageIndex(props.workflow))
const visible = computed(() => hasProgress(props.workflow))
const finished = computed(() => props.workflow.status === 'SUCCEEDED')
</script>

<template>
  <section class="workflow-progress" aria-label="实验阶段进度">
    <div class="progress-heading">
      <strong>{{ visible ? (finished ? '全部阶段已完成' : `当前阶段：${workflowStages[current]}`) : '阶段进度暂未显示' }}</strong>
      <span>{{ visible ? `第 ${current + 1} / ${workflowStages.length} 阶段` : '等待有效作业状态' }}</span>
    </div>
    <div class="stage-scroll">
      <div class="stage-ruler" :class="{ inactive: !visible, finished }">
        <div class="ruler-track" role="progressbar" aria-label="工作流阶段进度"
          :aria-valuenow="visible ? current : 0" :aria-valuemax="4" aria-valuemin="0"
          :aria-valuetext="visible ? workflowStages[current] : '暂无有效进度'">
          <span :style="{ width: visible ? `${current * 25}%` : '0%' }"></span>
        </div>
        <ol class="ruler-stages">
          <li v-for="(stage, index) in workflowStages" :key="stage"
            :class="{ done: visible && (index < current || finished), current: visible && index === current && !finished }"
            :aria-current="visible && index === current && !finished ? 'step' : undefined">
            <i>{{ visible && (index < current || finished) ? '✓' : index + 1 }}</i>
            <strong>{{ stage }}</strong>
            <small>{{ !visible ? '—' : (index < current || finished) ? '已完成' : index === current ? '当前阶段' : '待执行' }}</small>
          </li>
        </ol>
      </div>
    </div>
    <small class="progress-note">按作业状态更新阶段，非训练步数或耗时百分比。</small>
  </section>
</template>
