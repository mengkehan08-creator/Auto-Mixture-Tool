<script setup>
import { computed } from 'vue'
import { hasProgress, stageIndex, workflowStages as allStages } from '../workflow-state'
import StrategyProgress from './StrategyProgress.vue'
const props = defineProps({ workflow: { type: Object, required: true } })
const workflowStages = computed(() => props.workflow.jobs?.length === 2
  ? ['配比提交', '配比采样', '训练提交', props.workflow.jobs[1].module === 'training-evaluation' ? '训练评测' : '模型训练', '全部完成'] : allStages)
const current = computed(() => Math.min(stageIndex(props.workflow), workflowStages.value.length - 1))
const visible = computed(() => hasProgress(props.workflow))
const finished = computed(() => props.workflow.status === 'SUCCEEDED')
</script>

<template>
  <section class="workflow-progress" aria-label="实验阶段进度">
    <StrategyProgress v-if="workflow.pipeline_version === 4" :workflow="workflow" />
    <template v-else>
    <div class="progress-heading">
      <strong>{{ visible ? (finished ? '全部阶段已完成' : `当前阶段：${workflowStages[current]}`) : '阶段进度暂未显示' }}</strong>
      <span>{{ visible ? `第 ${current + 1} / ${workflowStages.length} 阶段` : '等待有效作业状态' }}</span>
    </div>
    <div class="stage-scroll">
      <div class="stage-ruler" :class="{ inactive: !visible, finished }">
        <div class="ruler-track" role="progressbar" aria-label="工作流阶段进度"
          :style="{ left: `${50 / workflowStages.length}%`, width: `${100 - 100 / workflowStages.length}%` }"
          :aria-valuenow="visible ? current : 0" :aria-valuemax="workflowStages.length - 1" aria-valuemin="0"
          :aria-valuetext="visible ? workflowStages[current] : '暂无有效进度'">
          <span :style="{ width: visible ? `${current * 100 / (workflowStages.length - 1)}%` : '0%' }"></span>
        </div>
        <ol class="ruler-stages" :style="{ gridTemplateColumns: `repeat(${workflowStages.length}, 1fr)` }">
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
    </template>
  </section>
</template>
