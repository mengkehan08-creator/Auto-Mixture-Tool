let nextId = 1

export const strategyOptions = [
  { value: 'quadmix', label: 'QuaDMix 算法', description: '内置算法 · 可独立运行' },
  { value: 'manual', label: '人工配比', description: '内置方法或完整策略脚本' },
  { value: 'random', label: '随机配比', description: '内置方法或完整策略脚本' },
]

export const stepOptions = [
  { id: 1, label: '配比策略' },
  { id: 2, label: '训练配置' },
  { id: 3, label: '评测配置' },
  { id: 4, label: '确认提交' },
]

export function createStrategy(type = 'quadmix') {
  const common = { id: nextId++, type }

  if (type === 'manual') {
    return {
      ...common,
      name: '专家人工配比',
      source: 'builtin',
      builtinMethod: 'default_manual',
      scriptObsUri: '',
      ratios: { '数学': 0.6, '物理': 0.15, '化学': 0.125, '生物学': 0.125 },
      seed: 42,
    }
  }

  if (type === 'random') {
    return {
      ...common,
      name: '均匀随机配比',
      source: 'builtin',
      builtinMethod: 'uniform',
      scriptObsUri: '',
      seed: 42,
    }
  }

  return {
    ...common,
    name: 'QuaDMix 自动配比',
    proxyExperiments: 16,
    proxySteps: 15,
    searchCount: 1000,
    seed: 42,
    deviceType: 'NPU',
    devicesPerNode: 8,
  }
}

export const createTrainingConfig = () => ({
  frameworkSource: 'builtin',
  framework: 'NanoChat',
  frameworkObsUri: 'obs://bucket/path/nanochat-npu/',
  modelSource: 'builtin',
  model: 'NanoChat-Base',
  modelObsUri: 'obs://bucket/path/nanochat_model_dir/',
  baseModelTag: 'd24',
  targetParamDataRatio: 0.5,
  devicesPerNode: 8,
  nodes: 2,
})

export const createEvaluationConfig = () => ({
  dataset: {
    enabled: true,
    source: 'builtin',
    names: ['stem'],
    obsUri: '',
  },
  api: {
    enabled: false,
    endpoint: '',
    model: '',
    key: '',
  },
})

export const createRuntimeConfig = () => ({
  modelarts: { endpoint: '', region: '', authorization: '', workspace_id: '', workspace_name: 'aifm-lmdt-exp_MA_workspace', image_url: '', image_repo_id: '', flavor_id: 'modelarts.pool.visual.8xlarge', pool_id: '' },
  experimentName: '',
  inputDataObsUri: 'obs://bucket/path/prepared_parquet/',
  outputRootObsUri: 'obs://bucket/path/chengchao/',
  mixingNodes: 2,
  codeObsUri: 'obs://bucket/path/Auto-Mixture-Tool/',
  quadmixTokenizerObsUri: 'obs://bucket/path/gpt-neox-tokenizer/',
  proxyValidationObsUri: 'obs://bucket/path/proxy_validation/',
  evalBundleObsUri: 'obs://bucket/path/eval_bundle/',
  pythonWheelsObsUri: 'obs://bucket/path/python_wheels/',
})
