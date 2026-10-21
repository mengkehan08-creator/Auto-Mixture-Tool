import { createRuntimeConfig, createTrainingConfig, createEvaluationConfig, createStrategy, trainingParameters } from './data/defaults.js'
import { upperOnlyBounds } from './budget-estimates.js'
import { normalizeEvaluationTasks } from './evaluation-selection.js'

export function copyWorkflow(config) {
  const runtime = createRuntimeConfig()
  const training = createTrainingConfig()
  const evaluation = createEvaluationConfig()
  const resources = config.resources || {}
  Object.assign(runtime, {
    maxActiveJobs: config.max_active_jobs ?? 8,
    priority: config.priority ?? 1,
    commands: config.commands ? { ...config.commands } : null,
    experimentName: config.experiment_name || '', inputDataObsUri: config.input_data_obs_uri,
    outputRootObsUri: config.output_root_obs_uri, mixingNodes: config.mixing_nodes,
    codeObsUri: resources.code_obs_uri, quadmixTokenizerObsUri: resources.quadmix_tokenizer_obs_uri,
    proxyValidationObsUri: resources.proxy_validation_obs_uri, evalBundleObsUri: resources.eval_bundle_obs_uri,
    pythonWheelsObsUri: resources.python_wheels_obs_uri,
    modelarts: { ...runtime.modelarts, ...config.modelarts, authorization: '' },
  })
  Object.assign(training, {
    outputObsUri: config.training.output_obs_uri || '',
    nodes: config.training_nodes ?? training.nodes,
    priority: config.strategies[0]?.training_priority ?? training.priority,
    frameworkObsUri: resources.nanochat_repo_obs_uri,
    modelObsUri: resources.nanochat_model_obs_uri, model: config.training.model || 'NanoChat-Base',
    baseModelTag: config.training.base_model_tag || 'd24',
    targetParamDataRatio: config.training.target_param_data_ratio,
    devicesPerNode: 8,
    tokenBudget: config.training.token_budget ?? training.tokenBudget,
    totalBatchSize: config.training.total_batch_size ?? null,
    batchSizeMode: config.training.batch_size_mode ?? (config.training.total_batch_size != null ? 'fixed' : 'auto'),
    deviceBatchSize: config.training.device_batch_size ?? 1,
    evalEvery: config.training.eval_every ?? -1,
    coreMetricEvery: config.training.core_metric_every ?? -1,
  })
  runtime.offlineResources = config.offline_resources ? structuredClone(config.offline_resources) :
    runtime.offlineResources.map(item => ({ ...item, uri: resources[item.role] || item.uri }))
  evaluation.outputObsUri = config.evaluation.output_obs_uri || ''
  evaluation.obsPackages = structuredClone(config.evaluation.obs_packages || [])
  evaluation.api.enabled = config.evaluation.automatic_api_requested === true
  evaluation.nodes = config.evaluation_nodes ?? 1
  evaluation.devicesPerNode = 8
  evaluation.coreEvalBatchSize = config.evaluation.core_eval_batch_size ?? 16
  evaluation.maxPerTask = config.evaluation.max_per_task ?? -1
  evaluation.modelIds = [...(config.evaluation.model_ids || [])]
  evaluation.priority = config.evaluation.priority ?? 2
  evaluation.dataset = { enabled: Boolean(config.evaluation.datasets.length || evaluation.obsPackages.length), source: 'obs',
    names: normalizeEvaluationTasks(config.evaluation.datasets), obsUri: resources.eval_bundle_obs_uri }
  const strategies = config.strategies.map(item => ({ ...createStrategy(item.type),
    name: item.name, seed: item.seed ?? 42, proxyExperiments: item.proxy_experiments,
    proxySteps: item.proxy_steps ?? 15, searchCount: item.search_count ?? 5000, devicesPerNode: 8,
    ...(item.sampling_bounds ? { samplingBounds: upperOnlyBounds(item.sampling_bounds) } : {}),
    ratios: item.ratios ? { ...item.ratios } : undefined,
    source: item.script_obs_uri || item.script_upload ? 'script' : 'builtin', scriptObsUri: item.script_obs_uri || '',
    scriptInput: item.script_upload ? 'upload' : 'obs', scriptUpload: item.script_upload ? structuredClone(item.script_upload) : null,
    scriptConfig: structuredClone(item.script_config || {}),
    mixingNodes: item.mixing_nodes ?? config.mixing_nodes,
    trainingNodes: item.training_nodes ?? config.training_nodes,
    trainingNodesOverride: item.training_nodes != null && item.training_nodes !== training.nodes ? item.training_nodes : null,
    mixingPriority: item.mixing_priority ?? 2,
    trainingPriority: item.training_priority ?? 2,
    trainingFrameworkSource: item.training_framework_source ?? 'builtin',
    trainingFrameworkObsUri: item.training_framework_obs_uri || '',
    mixingJobName: '', trainingJobName: '', modelName: item.model_name || '',
    mixingCommand: item.mixing_command?.trim() ? item.mixing_command : (config.commands?.mixing ?? null),
    trainingCommand: item.training_command?.trim() ? item.training_command : (config.commands?.training ?? null),
    trainingOverrides: { ...trainingParameters(training), ...structuredClone(item.training || {}), devices_per_node: 8 },
  }))
  return { runtime, training, evaluation, strategies }
}
