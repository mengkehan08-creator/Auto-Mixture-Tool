import { createEvaluationConfig, createRuntimeConfig, createStrategy, createTrainingConfig } from './data/defaults.js'

export const draftKey = 'auto-mixture:experiment-draft:v1'
const maxDraftBytes = 1024 * 1024
const runtimeFields = ['maxActiveJobs', 'priority', 'offlineResources', 'commands', 'autoCommandDefaults', 'modelarts',
  'experimentName', 'inputDataObsUri', 'outputRootObsUri', 'mixingNodes', 'codeObsUri',
  'quadmixTokenizerObsUri', 'proxyValidationObsUri', 'evalBundleObsUri', 'pythonWheelsObsUri']
const privateField = /^(authorization|password|credentials?|secret|api[_-]?key|access[_-]?key(?:[_-]?id)?|secret(?:[_-]?access)?[_-]?key|(?:(?:api|access|refresh)[_-]?)?token|__proto__|constructor|prototype)$/i
const publicValue = (key, value) => privateField.test(key) ? undefined : value
const object = value => value && typeof value === 'object' && !Array.isArray(value)

export function serializeDraft({ step, runtime, training, evaluation, strategies }) {
  return JSON.stringify({ version: 1, step, training,
    evaluation: { ...evaluation, api: { ...evaluation.api, key: '' } }, strategies,
    runtime: Object.fromEntries(runtimeFields.filter(key => key in runtime).map(key => [key, runtime[key]])),
  }, publicValue)
}

export function writeDraft(storage, serialized) {
  if (serialized.length > maxDraftBytes || new TextEncoder().encode(serialized).length > maxDraftBytes) throw new Error('草稿超过 1 MiB，无法保存；当前配置仍保留在页面中。')
  storage.setItem(draftKey, serialized)
}

export function readDraft(storage) {
  const raw = storage?.getItem(draftKey)
  if (!raw) return null
  if (raw.length > maxDraftBytes || new TextEncoder().encode(raw).length > maxDraftBytes) throw new Error('已保存草稿过大，请清空草稿后重新配置。')
  const saved = JSON.parse(raw, publicValue)
  if (saved?.version !== 1 || !Number.isInteger(saved.step) || saved.step < 1 || saved.step > 4 ||
      !object(saved.training) || !object(saved.runtime) || !object(saved.evaluation) ||
      !object(saved.evaluation.dataset) || !Array.isArray(saved.evaluation.dataset.names) ||
      !Array.isArray(saved.strategies) || !saved.strategies.length ||
      saved.strategies.some(item => !object(item) || !['quadmix', 'manual', 'random'].includes(item.type))) {
    throw new Error('已保存草稿格式不兼容，请清空草稿后重新配置。')
  }
  const runtime = createRuntimeConfig(), evaluation = createEvaluationConfig()
  return {
    step: saved.step,
    runtime: { ...runtime, ...saved.runtime, datasetEstimate: null,
      modelarts: { ...runtime.modelarts, ...saved.runtime.modelarts, authorization: '' } },
    training: { ...createTrainingConfig(), ...saved.training },
    evaluation: { ...evaluation, ...saved.evaluation,
      dataset: { ...evaluation.dataset, ...saved.evaluation.dataset },
      api: { ...evaluation.api, ...saved.evaluation.api, key: '' } },
    strategies: saved.strategies.map(item => {
      const defaults = createStrategy(item.type)
      return { ...defaults, ...item, id: defaults.id }
    }),
  }
}
