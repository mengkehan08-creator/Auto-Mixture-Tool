<script setup>
import dataScript from '../../../examples/datasets/quadmix_parquet.py?raw'
import manualScript from '../../../examples/strategies/manual_quality_first.py?raw'
import randomScript from '../../../examples/strategies/random_length_aware.py?raw'
import core from '../../../examples/evaluation/basic/core.yaml?raw'
import records from '../../../examples/evaluation/basic/eval_data/science.jsonl?raw'
import baseline from '../../../examples/evaluation/basic/eval_meta_data.csv?raw'
import { computed } from 'vue'
import { ArrowRight, BookOpen, Download, Info } from '@lucide/vue'
const props = defineProps({ kind: String })
defineEmits(['close'])
const titles = { dataset: 'QuaDMix 输入数据示例', evaluation: '评测包格式与支持范围', quadmix: 'QuaDMix 算法', manual: '人工配比', random: '随机配比' }
const guides = {
  quadmix: {
    tag: '算法寻找配比', headline: '先做小规模试验，再决定怎么选数据。',
    intro: '让算法尝试不同的数据组合，根据小模型的验证表现，寻找用于正式训练的配比。',
    steps: [['整理候选数据', '读取每篇文本的领域和质量分，形成不同的选取规则。'], ['试验与搜索', '用小模型做多次代理实验，再搜索预测表现较好的配比参数。'], ['生成训练子集', '按找到的规则抽取整篇文本，交给后续模型训练。']],
    example: '例如：算法比较不同数学、物理等数据组合的验证表现，再决定各类数据的选取权重；不是简单地只选质量分最高的文本。',
    use: '希望通过实验寻找配比，愿意投入额外计算资源。',
    caution: '最终采样量不是由代理实验步数直接决定的；同一篇文本可能被选中多次。搜索结果也不保证优于人工或随机策略。',
    output: '采样文本、实际配比和实验结果',
  },
  manual: {
    tag: '按指定比例选择', headline: '你定各领域的比例，工具自动选出文本。',
    intro: '把选数预算按设定比例分给各领域，再在每个领域内随机选取文档。无需运行代理实验。',
    steps: [['分配领域预算', '根据设定比例，计算各领域应选取多少数据。'], ['领域内选文本', '按随机种子打乱该领域文档，依次选取。'], ['核算并输出', '统计实际 Token 数，按预算上限裁剪，写出训练数据。']],
    example: '例如：给数学更多预算，就会优先保障数学数据的份额；领域内部默认随机选文档，不会自动优先选高质量文本。',
    use: '已有领域配比方案，想验证自己的经验或做受控对照。',
    caution: '按整篇文档选取，长度和裁剪会使实际 Token 比例与设定比例略有偏差。脚本可替换领域内的选文规则。',
    output: '采样文本、实际配比和数据统计',
  },
  random: {
    tag: '不预设领域比例', headline: '把候选文本打乱，随机选出一批。',
    intro: '所有候选文档参与随机选择，不按领域分配固定份额，也不按质量分优先选择。无需运行代理实验。',
    steps: [['汇总候选文本', '将各领域的可用文档放入同一个候选池。'], ['随机选文本', '按随机种子打乱文档，按预算依次选取。'], ['核算并输出', '统计实际 Token 数，按预算上限裁剪，写出训练数据。']],
    example: '例如：候选池里数学文档较多，随机结果中数学通常也较多。随机选文档，不代表每个领域各占相同份额。',
    use: '建立简单的对照基线，判断算法或人工配比是否带来收益。',
    caution: '不同随机种子可能产生不同子集。按文档随机，不等于按 Token 均匀抽样；脚本可替换默认选文规则。',
    output: '采样文本、实际配比和数据统计',
  },
}
const guide = computed(() => guides[props.kind])
function download(name, content) {
  const url = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = name; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>
<template>
  <div class="guide-backdrop" @click.self="$emit('close')" @keydown.esc="$emit('close')">
    <section class="guide-page" role="dialog" aria-modal="true" aria-labelledby="guide-title" tabindex="-1">
      <header><div class="guide-heading"><BookOpen :size="20" /><h2 id="guide-title">{{ titles[kind] }}</h2></div><button type="button" class="button secondary" autofocus @click="$emit('close')">返回配置</button></header>
      <div class="guide-content">
      <template v-if="kind === 'dataset'"><p>输入为 Parquet 目录。领域列 domain、正文 text、整数长度 char_count，以及五个数值质量分。领域编码须与 schema 的 domain_names 顺序一致。</p><p>校验全部分片的字段类型，并检查每片前 1000 条记录。原始 JSON 应先转换，校验按钮不会自动修改数据。</p><pre>{{ dataScript }}</pre><button class="button primary" @click="download('quadmix_parquet.py', dataScript)">下载数据示例脚本</button></template>
      <template v-else-if="kind === 'evaluation'">
        <p>支持按下述统一格式整理的文本选择题（如 MMLU、CMMLU、C-Eval、ARC、GPQA），以及使用现有 gsm8k / math 答案提取器的生成题。不能仅凭评测集名称判断兼容性。</p>
        <p>未经转换的原始数据、HumanEval / MBPP 代码执行、多模态、BLEU / ROUGE 等任务暂不支持。提交前读取挂载目录，检查任务定义、基线和全部 JSONL 记录；无法读取或不兼容时不提交作业。</p>
        <p>选择题：query 为问题，choices 为字符串数组，gold 为从 0 开始的正确选项索引。生成题：query 与 answer；core.yaml 使用 generation，并指定 answer_extractor: gsm8k 或 math。</p>
        <p>将 basic 目录整体上传 OBS，再填写该目录地址。以下为格式示例，不是正式评测数据。</p>
        <div v-for="item in [['core.yaml', core], ['eval_meta_data.csv', baseline], ['eval_data/science.jsonl', records]]" :key="item[0]"><h3>{{ item[0] }}</h3><pre>{{ item[1] }}</pre><button class="button secondary" @click="download(item[0].split('/').at(-1), item[1])">下载 {{ item[0] }}</button></div>
      </template>
      <template v-else-if="guide">
        <div class="guide-hero"><span class="guide-tag">{{ guide.tag }}</span><h3>{{ guide.headline }}</h3><p>{{ guide.intro }}</p></div>
        <h3 class="guide-section-title">怎么选数据</h3>
        <ol class="guide-steps"><li v-for="(step, i) in guide.steps" :key="step[0]"><span class="guide-step-number">0{{ i + 1 }}</span><h4>{{ step[0] }}</h4><p>{{ step[1] }}</p><ArrowRight v-if="i < 2" class="guide-arrow" :size="18" /></li></ol>
        <p class="guide-example">{{ guide.example }}</p>
        <div class="guide-facts"><section><span>适合什么情况</span><p>{{ guide.use }}</p></section><section><span>最后得到什么</span><p>{{ guide.output }}</p><small>子集是选出的文本集合，不是训练好的模型。</small></section></div>
        <div class="guide-caution"><Info :size="18" /><div><strong>使用前知道这件事</strong><p>{{ guide.caution }}</p></div></div>
        <details v-if="kind === 'quadmix'" class="guide-details"><summary>理解代理实验数、步数和采样量</summary><p>代理实验数：尝试多少组配比。代理实验步数：每个小模型训练多久。参数搜索次数：利用代理实验结果预测、比较多少组参数，不会为每组搜索参数都重新训练模型。</p><p>这些参数可能改变搜索得到的选取规则，但不能直接换算最终子集的 Token 数。采样量以本次最终输出文本经训练 Tokenizer 统计的结果为准；重复入选的文本也计入，并非去重后的数据量。</p></details>
        <details v-else class="guide-details"><summary>自定义选文规则 · 查看与下载脚本</summary><p>下载示例后修改，回到配置页选择上传脚本或填写 OBS 地址。只执行可信内部用户的 Python 代码。</p><p>{{ kind === 'manual' ? '本示例在各领域内优先选择长文档，不是按质量分排序；领域预算仍由配比设置控制。' : '本示例先按文档长度分桶，再在桶内随机打乱，与内置随机规则不同。' }}</p><button class="button primary" @click="download(kind === 'manual' ? 'manual_quality_first.py' : 'random_length_aware.py', kind === 'manual' ? manualScript : randomScript)"><Download :size="16" />下载策略脚本</button><p>接口：select(pool, context, config)。返回一维、无重复、未越界的整数索引；人工脚本对各领域分别调用。</p><pre>{{ kind === 'manual' ? manualScript : randomScript }}</pre></details>
      </template>
      </div>
    </section>
  </div>
</template>
<style scoped>
.guide-backdrop { position: fixed; inset: 0; z-index: 100; background: #15274680; backdrop-filter: blur(5px); padding: 4vh 4vw; display: grid; place-items: start center; }
.guide-page { width: min(960px, 100%); max-height: 92vh; overflow: auto; background: white; border-radius: 20px; box-shadow: 0 20px 80px #15274640; }
header { position: sticky; top: 0; z-index: 1; display: flex; justify-content: space-between; align-items: center; gap: 18px; padding: 20px 28px; border-bottom: 1px solid #e7edf5; background: #fffffffa; }
.guide-heading { display: flex; align-items: center; gap: 12px; color: #5071d2; }
.guide-heading h2 { font-size: 18px; }
.guide-content { padding: 24px 28px 28px; }
p { line-height: 1.8; color: #53647b; font-size: 14px; }
.guide-hero { padding: 24px; border: 1px solid #dce6fb; border-radius: 14px; background: linear-gradient(115deg, #eef3ff, #f8faff); }
.guide-tag { display: inline-block; color: #4165c2; font-size: 12px; font-weight: 600; letter-spacing: .5px; }
.guide-hero h3 { margin: 9px 0; color: #20395e; font-size: 24px; line-height: 1.5; }
.guide-hero p { margin: 0; max-width: 66ch; }
.guide-section-title { margin: 26px 0 14px; font-size: 15px; }
.guide-steps { list-style: none; padding: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
.guide-steps li { position: relative; padding: 18px; border: 1px solid #e3eaf3; border-radius: 12px; background: #fcfdff; }
.guide-step-number { color: #6d8cda; font-weight: 700; font-size: 13px; }
h4 { margin: 10px 0 6px; color: #2b4063; font-size: 15px; }
.guide-steps p { margin: 0; font-size: 13px; }
.guide-arrow { position: absolute; right: -19px; top: 28px; color: #9aadd1; background: white; }
.guide-example { padding: 0 2px; margin: 14px 0 22px; font-size: 13px; }
.guide-facts { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; padding: 20px 0; border-top: 1px solid #edf1f7; }
.guide-facts span { font-size: 13px; color: #2c486e; font-weight: 600; }
.guide-facts p { margin: 7px 0 0; }
.guide-facts small { font-size: 12px; color: #758298; }
.guide-caution { display: flex; align-items: flex-start; gap: 10px; padding: 16px 18px; border-radius: 12px; background: #fff8eb; color: #89602c; }
.guide-caution svg { flex-shrink: 0; margin-top: 2px; }
.guide-caution strong { font-size: 13px; }
.guide-caution p { margin: 4px 0 0; color: #7b674a; font-size: 13px; }
.guide-details { margin-top: 20px; padding: 16px 18px; border: 1px solid #e0e7f1; border-radius: 12px; }
summary { cursor: pointer; color: #395783; font-size: 14px; font-weight: 600; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 18px; border-radius: 12px; background: #f3f6fc; font-size: 13px; }
@media (max-width: 640px) { .guide-steps, .guide-facts { grid-template-columns: 1fr; } .guide-arrow { display: none; } .guide-content, header { padding: 18px; } .guide-hero { padding: 18px; } .guide-hero h3 { font-size: 20px; } }
</style>
