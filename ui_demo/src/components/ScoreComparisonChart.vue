<script setup>
import { computed } from 'vue'
import { formatScore, scoreRanking } from '../result-scores'
const props = defineProps({ models: Array, task: String })
const value = model => props.task ? model.metrics[props.task]?.accuracy : model.mean_accuracy
const ranking = computed(() => scoreRanking(props.models, value))
const width = computed(() => Math.max(560, props.models.length * 112 + 70))
const x = index => 70 + index * ((width.value - 90) / props.models.length) + (width.value - 90) / props.models.length / 2
const y = score => 242 - score * 206
const best = model => ranking.value.ids.includes(model.id)
const points = computed(() => props.models.map((model, index) => ({ model, index, score: value(model) })))
</script>
<template>
  <div class="comparison-chart" role="region" :aria-label="task ? `${task} 正确率柱状折线图` : '平均正确率柱状折线图'" tabindex="0">
    <svg :width="width" :style="{ width: models.length > 4 ? `${width}px` : '100%' }" :viewBox="`0 0 ${width} 292`" role="img" aria-label="柱高与折线节点表示相同正确率，红色为最高分">
      <g v-for="tick in [0, .25, .5, .75, 1]" :key="tick"><line x1="56" :x2="width - 12" :y1="y(tick)" :y2="y(tick)" stroke="#e5ebf6" /><text x="45" :y="y(tick) + 4" text-anchor="end" fill="#60718e" font-size="12">{{ tick * 100 }}%</text></g>
      <g v-for="{ model, index, score } in points" :key="model.id">
        <template v-if="typeof score === 'number'">
          <rect :x="x(index) - 23" :y="y(score)" width="46" :height="score * 206" rx="5" :fill="best(model) ? '#d33b50' : '#9cb2e8'"><title>{{ model.name }}：{{ formatScore(score) }}</title></rect>
          <line v-if="index > 0 && typeof points[index - 1].score === 'number'" :x1="x(index - 1)" :y1="y(points[index - 1].score)" :x2="x(index)" :y2="y(score)" stroke="#516ca6" stroke-width="2" />
          <circle :cx="x(index)" :cy="y(score)" r="5" :fill="best(model) ? '#b92339' : '#516ca6'" stroke="white" stroke-width="2" />
          <text :x="x(index)" :y="Math.max(17, y(score) - 12)" text-anchor="middle" :fill="best(model) ? '#b92339' : '#3b5278'" font-size="12" font-weight="600">{{ formatScore(score) }}</text>
        </template>
        <text :x="x(index)" y="270" text-anchor="middle" fill="#455c80" font-size="12">模型 {{ index + 1 }}</text>
      </g>
    </svg>
  </div>
  <div class="chart-legend"><span v-for="(model, index) in models" :key="model.id" :class="{ best: best(model) }"><i :style="{ background: best(model) ? '#d33b50' : '#9cb2e8' }"></i>{{ index + 1 }} · {{ model.name }} · {{ formatScore(value(model)) }}</span></div>
  <small class="chart-note">柱形与折线节点表示同一指标；连线仅辅助比较，不表示时间趋势。未记录的得分留空。</small>
</template>
<style scoped>
.comparison-chart { overflow-x: auto; max-width: 100%; background: #fbfcff; border-radius: 12px; }
.chart-legend { display: flex; flex-wrap: wrap; gap: 10px 18px; margin-top: 14px; font-size: 12px; color: #506380; }
.chart-legend span { overflow-wrap: anywhere; } .chart-legend i { display: inline-block; height: 8px; width: 8px; border-radius: 2px; margin-right: 5px; }
.best { color: #b92339; font-weight: 600; } .chart-note { display: block; margin-top: 12px; color: #6b7890; line-height: 1.8; }
</style>
