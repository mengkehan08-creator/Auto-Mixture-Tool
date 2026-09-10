<script setup>
import { computed } from 'vue'
import { strategyProgress } from '../strategy-progress.js'
const props = defineProps({ workflow: { type: Object, required: true } })
const graph = computed(() => strategyProgress(props.workflow))
const height = computed(() => Math.max(1, graph.value.branches.length) * 132 + 28)
const center = computed(() => height.value / 2 - 12)
const branchY = index => 68 + index * 132
const branchX = [220, 338, 456, 574]
const tailX = index => 696 + index * 112
const width = computed(() => tailX(graph.value.tail.length - 1) + 60)
const edgeState = (left, right) => left.state === 'done' && right.state === 'done' ? 'done' :
  left.state === 'done' && right.state === 'running' ? 'running' : 'waiting'
const symbol = state => ({ done: '✓', error: '!', blocked: '!', running: '●', waiting: '·' })[state]
</script>

<template>
  <div class="strategy-progress">
    <div class="progress-heading"><strong>{{ graph.finished ? '全部阶段已完成' : '实验流程进度' }}</strong><span>{{ graph.completed }} / {{ graph.branches.length }} 策略分支完成</span></div>
    <p class="graph-caption">各策略独立配比与训练，完成后汇合{{ workflow.jobs?.some(j => j.module === 'evaluation') ? '进入统一评测。' : '结束实验，本次未启用评测。' }}</p>
    <div class="graph-scroll" tabindex="0" role="region" aria-label="分支阶段刻度图，可横向滚动">
      <svg :viewBox="`0 0 ${width} ${height}`" :style="{ minWidth: `${width}px` }" role="img" aria-label="实验按策略分支，配比与训练完成后汇合的阶段进度">
        <g class="connectors" aria-hidden="true">
          <path :class="graph.start.state" :d="`M 52 ${center} H 112`" />
          <path v-if="graph.branches.length" :d="`M 112 ${branchY(0)} V ${branchY(graph.branches.length - 1)} M 638 ${branchY(0)} V ${branchY(graph.branches.length - 1)}`" />
          <path :class="graph.tail[0].state === 'done' ? 'done' : 'waiting'" :d="`M 638 ${center} H ${tailX(0)}`" />
          <g v-for="(branch, index) in graph.branches" :key="branch.id">
            <path :class="edgeState(graph.start, branch.points[0])" :d="`M 112 ${branchY(index)} H ${branchX[0]}`" />
            <line v-for="step in 3" :key="step" :x1="branchX[step - 1]" :x2="branchX[step]" :y1="branchY(index)" :y2="branchY(index)" :class="edgeState(branch.points[step - 1], branch.points[step])" />
            <path :class="branch.points.every(p => p.state === 'done') ? 'done' : 'waiting'" :d="`M ${branchX[3]} ${branchY(index)} H 638`" />
            <path v-for="tick in 27" :key="`tick-${tick}`" class="ruler-tick" :d="`M ${220 + tick * 12} ${branchY(index) - 4} v 8`" />
          </g>
          <line v-for="step in graph.tail.length - 1" :key="`tail-${step}`" :x1="tailX(step - 1)" :x2="tailX(step)" :y1="center" :y2="center" :class="edgeState(graph.tail[step - 1], graph.tail[step])" />
        </g>
        <g :transform="`translate(52, ${center})`" :class="['graph-point', graph.start.state]">
          <circle r="15" /><text class="point-symbol" y="5">{{ symbol(graph.start.state) }}</text><text y="39">实验启动</text><text class="point-detail" y="59">{{ graph.start.detail }}</text>
        </g>
        <g v-for="(branch, index) in graph.branches" :key="branch.id">
          <rect class="branch-label-bg" x="174" :y="branchY(index) - 55" width="450" height="26" rx="7" />
          <text class="branch-label" x="188" :y="branchY(index) - 37"><title>{{ branch.name }}</title>{{ index + 1 }} · {{ branch.name.length > 30 ? branch.name.slice(0, 30) + '…' : branch.name }}</text>
          <g v-for="(point, step) in branch.points" :key="step" :transform="`translate(${branchX[step]}, ${branchY(index)})`" :class="['graph-point', point.state]">
            <title>{{ branch.name }}：{{ point.label }}，{{ point.detail }}</title><circle r="15" /><text class="point-symbol" y="5">{{ symbol(point.state) }}</text><text y="39">{{ point.label }}</text><text class="point-detail" y="59">{{ point.detail }}</text>
          </g>
        </g>
        <g v-for="(point, index) in graph.tail" :key="point.label" :transform="`translate(${tailX(index)}, ${center})`" :class="['graph-point', point.state]">
          <title>{{ point.label }}：{{ point.detail }}</title><circle r="15" /><text class="point-symbol" y="5">{{ symbol(point.state) }}</text><text y="39">{{ point.label }}</text><text class="point-detail" y="59">{{ point.detail }}</text>
        </g>
      </svg>
    </div>
    <div class="graph-legend" aria-label="阶段状态图例"><span class="done">已完成 / 已复用</span><span class="running">运行中</span><span class="waiting">等待 / 排队</span><span class="error">失败 / 终止</span><span class="blocked">待处理</span></div>
    <small class="progress-note">刻度表示实际阶段状态，不代表训练步数或耗时百分比。作业链接与重试操作见下方。</small>
  </div>
</template>

<style scoped>
.graph-caption { color: var(--text-secondary); font-size: 13px; margin: 10px 0 20px; }
.graph-scroll { overflow-x: auto; border: 1px solid #e2e9f5; border-radius: 12px; background: #fff; padding: 18px 0; }
.graph-scroll:focus-visible { outline: 2px solid #5277df; outline-offset: 3px; }
svg { display: block; width: 100%; }
.connectors path, .connectors line { fill: none; stroke: #dce4ef; stroke-width: 4; stroke-linejoin: round; }
.connectors .done { stroke: #63b797; }
.connectors .running { stroke: #6689e6; }
.connectors .ruler-tick { stroke: #bbc8dc; stroke-width: 1; }
.graph-point { color: #65758e; }
.graph-point circle { fill: #f1f4f9; stroke: #d7e0ed; stroke-width: 2; }
.graph-point text { fill: currentColor; font-size: 12px; text-anchor: middle; font-weight: 600; }
.graph-point .point-symbol { font-size: 15px; }
.graph-point .point-detail { font-size: 10px; font-weight: 400; }
.done { color: #197254; }.running { color: #365fc7; }.error { color: #ba394d; }.blocked { color: #92600c; }.waiting { color: #65758e; }
.graph-point.done circle { fill: #e7f6ef; stroke: #83c6ac; }
.graph-point.running circle { fill: #edf2ff; stroke: #6689e6; stroke-width: 3; }
.graph-point.error circle { fill: #fff0f3; stroke: #e8a7b3; }
.graph-point.blocked circle { fill: #fff7e6; stroke: #e6c17d; }
.branch-label-bg { fill: #f4f7fc; }
.branch-label { fill: #3e5273; font-size: 12px; font-weight: 600; }
.graph-legend { display: flex; flex-wrap: wrap; gap: 12px 20px; margin-top: 16px; font-size: 12px; }
.graph-legend span { display: inline-flex; align-items: center; gap: 7px; }
.graph-legend span::before { content: ''; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
</style>
