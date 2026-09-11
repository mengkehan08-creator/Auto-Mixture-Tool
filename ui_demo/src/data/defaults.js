let nextId = 1
const obsRoot = 'obs://bucket-pangu-green-guangzhou/s00944147/l00916525/'

export const strategyOptions = [
  { value: 'quadmix', label: 'QuaDMix 算法', description: '内置算法 · 可独立运行' },
  { value: 'manual', label: '人工配比', description: '内置方法或完整策略脚本' },
  { value: 'random', label: '随机配比', description: '内置方法或完整策略脚本' },
]

export const stepOptions = [
  { id: 1, label: '配比策略' },
  { id: 2, label: '训练配置' },
  { id: 3, label: '评测配置' },
  { id: 4, label: '任务配置' },
]

export function createStrategy(type = 'quadmix') {
  const common = { id: nextId++, type, mixingNodes: type === 'quadmix' ? 2 : 1, trainingNodes: 2,
    mixingJobName: '', trainingJobName: '', modelName: '', mixingPriority: 2, trainingPriority: 2,
    trainingFrameworkSource: 'builtin', trainingFrameworkObsUri: '',
    trainingOverrides: trainingParameters(), mixingCommand: null, trainingCommand: null }

  if (type === 'manual') {
    return {
      ...common,
      name: '',
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
      name: '',
      source: 'builtin',
      builtinMethod: 'uniform',
      scriptObsUri: '',
      seed: 42,
    }
  }

  return {
    ...common,
    name: '',
    proxyExperiments: 16,
    proxySteps: 15,
    searchCount: 5000,
    seed: 42,
    deviceType: 'NPU',
    devicesPerNode: 8,
  }
}

export const createTrainingConfig = () => ({
  outputObsUri: `${obsRoot}chengchao/models/`,
  frameworkSource: 'builtin',
  framework: 'NanoChat',
  frameworkObsUri: `${obsRoot}backup_0810/work/nanochat-npu/`,
  modelSource: 'builtin',
  model: 'NanoChat-Base',
  modelObsUri: `${obsRoot}backup_0810/work/nanochat_model_dir/`,
  baseModelTag: 'd24',
  targetParamDataRatio: 0.5,
  tokenBudget: 401395843,
  deviceBatchSize: 1,
  evalEvery: -1,
  coreMetricEvery: -1,
  devicesPerNode: 8,
  nodes: 2,
})

export function trainingParameters(config = createTrainingConfig()) {
  return { token_budget: config.tokenBudget, device_batch_size: config.deviceBatchSize,
    devices_per_node: config.devicesPerNode, eval_every: config.evalEvery, core_metric_every: config.coreMetricEvery }
}

export const createEvaluationConfig = () => ({
  modelIds: [], jobName: '', priority: 2,
  obsPackages: [],
  nodes: 1,
  devicesPerNode: 8,
  coreEvalBatchSize: 16,
  maxPerTask: -1,
  outputObsUri: `${obsRoot}chengchao/reports/`,
  dataset: {
    enabled: true,
    source: 'builtin',
    names: [...stemTasks],
    obsUri: `${obsRoot}eval_bundle/`,
  },
  api: {
    enabled: false,
    endpoint: '',
    model: '',
    key: '',
  },
})

export const createRuntimeConfig = () => ({
  maxActiveJobs: 8,
  priority: 1,
  offlineResources: [
    { role: 'code_obs_uri', name: 'code_dir', uri: `${obsRoot}Auto-Mixture-Tool/` },
    { role: 'quadmix_tokenizer_obs_uri', name: 'quadmix_tokenizer_dir', uri: `${obsRoot}gpt-neox-tokenizer/` },
    { role: 'proxy_validation_obs_uri', name: 'proxy_validation_dir', uri: `${obsRoot}AMT_old/data/` },
    { role: 'eval_bundle_obs_uri', name: 'eval_bundle_dir', uri: `${obsRoot}eval_bundle/` },
    { role: 'python_wheels_obs_uri', name: 'python_wheels_dir', uri: `${obsRoot}python_wheels/` },
  ],
  commands: null,
  modelarts: { endpoint: '', region: '', authorization: '', workspace_id: '', workspace_name: 'aifm-lmdt-exp_MA_workspace', image_url: '', image_repo_id: '', flavor_id: 'modelarts.pool.visual.8xlarge', pool_id: '' },
  experimentName: '',
  inputDataObsUri: `${obsRoot}chengchao/prepared_parquet_57ffce0ca0a2/`,
  outputRootObsUri: `${obsRoot}chengchao/`,
  mixingNodes: 2,
  codeObsUri: `${obsRoot}Auto-Mixture-Tool/`,
  quadmixTokenizerObsUri: `${obsRoot}gpt-neox-tokenizer/`,
  proxyValidationObsUri: `${obsRoot}AMT_old/data/`,
  evalBundleObsUri: `${obsRoot}eval_bundle/`,
  pythonWheelsObsUri: `${obsRoot}python_wheels/`,
})
import { stemTasks } from '../evaluation-selection.js'
