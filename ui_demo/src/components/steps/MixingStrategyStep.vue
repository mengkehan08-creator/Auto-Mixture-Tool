<script setup>
import { createStrategy } from '../../data/defaults'
import StrategyCard from '../strategy/StrategyCard.vue'
import QuadMixBatchDialog from '../strategy/QuadMixBatchDialog.vue'
import { ref } from 'vue'
import ResourceGuide from '../ResourceGuide.vue'
import ResourceCheck from '../ResourceCheck.vue'
import { formatTokens } from '../../budget-estimates'
const showGuide = ref(false)
const batchSource = ref(null)
const batchNotice = ref('')

const props = defineProps({
  strategies: { type: Array, required: true },
  runtime: { type: Object, required: true },
  trainingNodes: { type: Number, default: 2 },
})

function changeType(index, type) {
  props.strategies.splice(index, 1, createStrategy(type))
}

function applyBatch({ strategies, placement }) {
  const index = props.strategies.findIndex(s => s.id === batchSource.value.id)
  if (index < 0) return
  if (placement === 'replace') props.strategies.splice(index, 1, ...strategies)
  else props.strategies.push(...strategies)
  batchNotice.value = `已${placement === 'replace' ? '替换当前策略，生成' : '追加'} ${strategies.length} 项 QuaDMix 策略，共 ${strategies.length} 个配比作业和 ${strategies.length} 个对应训练作业。尚未提交。`
  batchSource.value = null
}

</script>

<template>
  <section class="step-panel">
    <div class="section-title-row">
      <div><h2>配比与采样配置</h2><p>每项策略创建独立配比作业，可并行运行。各自完成后自动提交对应训练作业。</p></div>
    </div>

    <div class="config-block">
      <div class="section-title-row"><h3>数据与作业输出</h3><button class="button secondary" type="button" @click="showGuide = true">数据示例</button></div>
      <div class="form-grid two-cols">
        <label class="field"><span>实验名称（可选）</span><textarea rows="2" v-model="runtime.experimentName" placeholder="留空则按启动时间生成" ></textarea></label>
        <label class="field"><span>输入 Parquet 数据 OBS 地址</span><textarea rows="2" v-model="runtime.inputDataObsUri" placeholder="obs://bucket/path/prepared_parquet/" ></textarea></label>
        <label class="field"><span>实验输出目录（可自定义）</span><textarea rows="2" v-model="runtime.outputRootObsUri" placeholder="obs://bucket/path/chengchao/" ></textarea><small>可选择任意有写入权限的 OBS 桶和目录。不支持本地文件夹或控制台网页链接。</small></label>
      </div>
      <ResourceCheck kind="dataset" :uri="runtime.inputDataObsUri" @checked="runtime.datasetEstimate = $event" />
      <div v-if="runtime.datasetEstimate?.ready" class="path-preview">
        数据文件大小：{{ (runtime.datasetEstimate.size_bytes / 1024 ** 3).toFixed(3) }} GiB · 输入数据集预计 Token 数：{{ formatTokens(runtime.datasetEstimate.estimated_tokens) }}
        <br />按每片随机至多 3 条文本的平均长度 × 该片文档数 ÷ 4 汇总估算，与训练预算无关。抽样量较小，中文、代码及长度差异大的数据可能偏差明显。
      </div>
      <p class="path-preview">输出预览：<code>{{ runtime.outputRootObsUri.replace(/\/$/, '') }}/runs/实验名-时间-编号/strategies/策略编号/</code>，各策略独立保存配比、采样和训练日志。</p>
    </div>

    <p v-if="batchNotice" class="path-preview" role="status">{{ batchNotice }}</p>
    <StrategyCard
      v-for="(strategy, index) in strategies"
      :key="strategy.id"
      :strategy="strategy"
      :index="index"
      :removable="strategies.length > 1"
      :dataset-tokens="runtime.datasetEstimate?.estimated_tokens"
      @remove="strategies.splice(index, 1)"
      @change-type="changeType(index, $event)"
      @batch="batchSource = strategy"
    />
    <ResourceGuide v-if="showGuide" kind="dataset" @close="showGuide = false" />
    <QuadMixBatchDialog v-if="batchSource" :source="batchSource" :default-training-nodes="trainingNodes" @close="batchSource = null" @apply="applyBatch" />
  </section>
</template>
