<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Layers, X, ArrowRight, RotateCcw } from '@lucide/vue'
import { batchExample, planQuadMixBatch, materializeQuadMixBatch } from '../../quadmix-batch.js'
import { samplingFields } from '../../budget-estimates.js'
import { parameterName } from '../../strategy-names.js'

const props = defineProps({ source: { type: Object, required: true } })
const emit = defineEmits(['close', 'apply'])
const dialog = ref(null)
const settings = reactive(batchExample())
const placement = ref('replace')
const excluded = ref([])
const plan = computed(() => {
  try { return { rows: planQuadMixBatch(props.source, settings), error: '' } }
  catch (error) { return { rows: [], error: error.message } }
})
watch(plan, () => { excluded.value = [] })
const selected = computed(() => plan.value.rows.filter(row => !excluded.value.includes(row.key)))
const totalExperiments = computed(() => selected.value.reduce((sum, row) => sum + row.proxyExperiments, 0))
const field = computed(() => samplingFields.find(f => f.key === settings.parameter))
const symbol = computed(() => field.value.label.split(' · ')[0])
const inherited = computed(() => samplingFields.filter(f => f.key !== settings.parameter))
const modes = { upper: '搜索上限', lower: '搜索下限', fixed: '固定值' }
function toggle(key) {
  excluded.value = excluded.value.includes(key) ? excluded.value.filter(k => k !== key) : [...excluded.value, key]
}
function apply() {
  if (plan.value.error || !selected.value.length) return
  emit('apply', { strategies: materializeQuadMixBatch(props.source, selected.value), placement: placement.value })
}
onMounted(() => dialog.value.showModal())
onBeforeUnmount(() => dialog.value?.close())
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="quadmix-batch-dialog" aria-labelledby="batch-title" @cancel.prevent="emit('close')">
      <header class="batch-header">
        <div class="batch-title"><span class="batch-icon"><Layers :size="22" /></span><div><h2 id="batch-title">QuaDMix 批量配置</h2><p>设置变化项，其他配置沿用当前策略。</p></div></div>
        <button type="button" class="button secondary close-button" aria-label="关闭批量配置" @click="emit('close')"><X :size="18" /></button>
      </header>
      <div class="batch-body">
        <div class="batch-explanation"><strong>控制变量，更快对比</strong><span>一个值保持该项设置一致，多个值生成全部组合。先预览，再加入；此处不会启动云端作业。</span></div>
        <div class="batch-layout">
          <section class="batch-inputs">
            <div class="batch-section-title"><h3>变化参数</h3><button class="button secondary" type="button" @click="Object.assign(settings, batchExample())"><RotateCcw :size="14" />载入示例</button></div>
            <label class="field"><span>代理实验数</span><input v-model="settings.experiments" placeholder="100, 300, 500" /><small>多个值用逗号分隔，重复值自动合并。</small></label>
            <label class="field"><span>代理实验步数</span><input v-model="settings.steps" placeholder="5000" /></label>
            <div class="form-grid two-cols">
              <label class="field"><span>扫描参数</span><select v-model="settings.parameter"><option v-for="item in samplingFields" :key="item.key" :value="item.key">{{ item.label }}</option></select></label>
              <label class="field"><span>修改方式</span><select v-model="settings.mode"><option v-for="(label, mode) in modes" :key="mode" :value="mode">{{ label }}</option></select></label>
            </div>
            <label class="field"><span>{{ symbol }} {{ modes[settings.mode] }}取值</span><textarea v-model="settings.values" rows="2" placeholder="0.1, 0.15, 0.2, 0.25, 0.3"></textarea><small v-if="settings.mode === 'fixed'">上下限均设为此值，该参数不再参与搜索。</small><small v-else>另一侧边界保持为 {{ source.samplingBounds[field.key][settings.mode === 'upper' ? 0 : 1] }}。</small></label>
            <div class="inherited-settings"><h4>保持一致</h4><dl><div><dt>参数搜索次数 / 随机种子</dt><dd>{{ source.searchCount }} / {{ source.seed }}</dd></div><div v-for="item in inherited" :key="item.key"><dt>{{ item.label.split(' · ')[0] }} 搜索范围</dt><dd>{{ source.samplingBounds[item.key].join(' ～ ') }}</dd></div><div><dt>配比 / 训练节点数</dt><dd>{{ source.mixingNodes }} / {{ source.trainingNodes }}</dd></div></dl><p>数据、训练配置及评测设置不变。作业与模型名称重新自动生成；命令沿用当前策略，若曾写死参数，请在任务配置中调整。</p></div>
          </section>
          <section class="batch-preview">
            <div class="batch-section-title"><h3>组合预览</h3><span>本批次 {{ plan.rows.length }} 个组合</span></div>
            <div class="batch-metrics" aria-live="polite"><div><strong>{{ selected.length }}</strong><span>已选策略</span></div><div><strong>{{ selected.length * 2 }}</strong><span>配比 + 训练作业</span></div><div><strong>{{ totalExperiments.toLocaleString() }}</strong><span>代理实验总数</span></div></div>
            <p v-if="plan.error" class="batch-error" role="alert">{{ plan.error }}</p>
            <template v-else>
              <div class="batch-selection"><span>取消勾选可跳过组合</span><button type="button" class="button secondary" @click="excluded = selected.length === plan.rows.length ? plan.rows.map(row => row.key) : []">{{ selected.length === plan.rows.length ? '取消全选' : '全选' }}</button></div>
              <div class="batch-table-scroll"><table><thead><tr><th>选择</th><th>{{ symbol }} 范围</th><th>实验数</th><th>步数</th><th>自动名称前缀</th></tr></thead><tbody><tr v-for="(row, index) in plan.rows" :key="row.key" :class="{ excluded: excluded.includes(row.key) }"><td><input type="checkbox" :checked="!excluded.includes(row.key)" :aria-label="`选择组合 ${index + 1}`" @change="toggle(row.key)" /></td><td>{{ row.samplingBounds[settings.parameter].join(' ～ ') }}</td><td>{{ row.proxyExperiments }}</td><td>{{ row.proxySteps }}</td><td><code>{{ parameterName({ type: 'quadmix', ...row }) }}</code></td></tr></tbody></table></div>
              <p class="batch-note">正式名称在提交时追加时间，重名自动区分。每项策略独立配比、对应独立训练，全部成功后按原配置汇总评测。</p>
            </template>
          </section>
        </div>
      </div>
      <footer class="batch-footer"><label class="placement-label"><span>加入方式</span><select v-model="placement" aria-label="批量策略加入方式"><option value="replace">替换当前 QuaDMix 策略</option><option value="append">追加并保留当前策略</option></select></label><div><button type="button" class="button secondary" @click="emit('close')">取消</button><button type="button" class="button primary" :disabled="!!plan.error || !selected.length" @click="apply">确认加入 {{ selected.length }} 项策略<ArrowRight :size="16" /></button></div></footer>
    </dialog>
  </Teleport>
</template>

<style scoped>
.quadmix-batch-dialog { width: min(1160px, calc(100vw - 40px)); max-height: calc(100dvh - 40px); padding: 0; border: 1px solid #dce5f4; border-radius: 20px; color: #253d60; background: #fff; box-shadow: 0 24px 90px #172c5038; overflow-y: auto; }
.quadmix-batch-dialog::backdrop { background: #172c5066; backdrop-filter: blur(3px); }
.batch-header, .batch-footer { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding: 20px 26px; background: #fff; position: sticky; z-index: 2; }
.batch-header { top: 0; border-bottom: 1px solid #e4ebf5; } .batch-footer { bottom: 0; border-top: 1px solid #e4ebf5; }
.batch-title { display: flex; align-items: center; gap: 14px; } .batch-icon { display: grid; place-items: center; width: 46px; height: 46px; border-radius: 14px; background: #edf2ff; color: #5073d9; }
h2, h3, h4 { margin: 0; } h2 { font-size: 20px; } h3 { font-size: 15px; } h4 { font-size: 13px; } .batch-title p { margin: 5px 0 0; font-size: 13px; color: #70819a; }
.batch-body { padding: 22px 26px; } .batch-explanation { display: flex; gap: 14px; flex-wrap: wrap; padding: 14px 18px; background: #eff5ff; border: 1px solid #dce7fb; border-radius: 12px; font-size: 13px; color: #536d96; margin-bottom: 22px; } .batch-explanation strong { color: #365ba2; }
.batch-layout { display: grid; grid-template-columns: minmax(280px, .8fr) minmax(0, 1.2fr); gap: 26px; } .batch-inputs > .field, .batch-inputs > .form-grid { margin-bottom: 16px; }
.batch-section-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; min-height: 36px; margin-bottom: 14px; } .batch-section-title > span, .batch-selection > span { color: #7788a1; font-size: 12px; }
.batch-section-title .button, .batch-selection .button { padding: 6px 10px; font-size: 12px; min-height: 30px; }
.field small { line-height: 1.65; } .field select { text-overflow: clip; } .batch-inputs .two-cols { grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 12px; }
.inherited-settings { padding: 16px; background: #f7f9fd; border: 1px solid #e4ebf5; border-radius: 12px; } dl { margin: 10px 0; } dl > div { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; font-size: 12px; } dt { color: #72839b; } dd { margin: 0; overflow-wrap: anywhere; } .inherited-settings p, .batch-note { font-size: 12px; color: #6e809a; line-height: 1.8; margin: 10px 0 0; }
.batch-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid #dfe8f7; border-radius: 12px; padding: 16px 8px; background: linear-gradient(120deg, #f0f5ff, #f9fbff); } .batch-metrics > div { display: grid; gap: 6px; text-align: center; border-right: 1px solid #dfe8f7; } .batch-metrics > div:last-child { border-right: 0; } .batch-metrics strong { font-size: 24px; color: #4769ca; font-variant-numeric: tabular-nums; } .batch-metrics span { font-size: 11px; color: #73839b; }
.batch-selection { display: flex; justify-content: space-between; align-items: center; margin: 14px 0 8px; } .batch-table-scroll { max-height: 400px; overflow: auto; border: 1px solid #e2eaf5; border-radius: 12px; } table { width: 100%; border-collapse: collapse; font-size: 12px; } th { position: sticky; top: 0; background: #f3f6fc; color: #637894; text-align: left; } th, td { padding: 11px 10px; border-bottom: 1px solid #eaf0f7; white-space: nowrap; } tbody tr:last-child td { border-bottom: 0; } tbody tr:nth-child(even) { background: #fbfcff; } tr.excluded { opacity: .45; } td input { width: 16px; height: 16px; accent-color: #5377e2; cursor: pointer; } code { font-size: 11px; color: #466494; }
.batch-error { padding: 14px 16px; color: #b42335; background: #fff2f3; border-radius: 12px; line-height: 1.7; font-size: 13px; }
.batch-footer > div { display: flex; gap: 10px; } .placement-label { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #718098; } .placement-label > span { white-space: nowrap; } .placement-label select { padding: 9px 12px; border: 1px solid #d8e3f2; border-radius: 9px; background: white; color: #355071; font: inherit; }
@media (max-width: 850px) { .batch-layout { grid-template-columns: 1fr; } .batch-footer { flex-wrap: wrap; } .batch-footer > div { margin-left: auto; } }
@media (max-width: 540px) { .quadmix-batch-dialog { width: calc(100vw - 16px); max-height: calc(100dvh - 16px); } .batch-body, .batch-header, .batch-footer { padding: 16px; } .batch-icon { display: none; } .batch-inputs .two-cols { grid-template-columns: 1fr; } .placement-label { flex-wrap: wrap; } }
</style>
