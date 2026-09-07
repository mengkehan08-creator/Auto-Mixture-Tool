import { createRuntimeConfig, createTrainingConfig, createEvaluationConfig, createStrategy } from './data/defaults.js'

export function copyWorkflow(config) {
  const runtime = createRuntimeConfig()
  const training = createTrainingConfig()
  const evaluation = createEvaluationConfig()
  const resources = config.resources || {}
  Object.assign(runtime, {
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
    nodes: config.training_nodes, frameworkObsUri: resources.nanochat_repo_obs_uri,
    modelObsUri: resources.nanochat_model_obs_uri, model: config.training.model || 'NanoChat-Base',
    baseModelTag: config.training.base_model_tag || 'd24',
    targetParamDataRatio: config.training.target_param_data_ratio,
    devicesPerNode: config.training.devices_per_node,
    numIterations: config.training.num_iterations ?? 0,
    deviceBatchSize: config.training.device_batch_size ?? 1,
    evalEvery: config.training.eval_every ?? -1,
    coreMetricEvery: config.training.core_metric_every ?? -1,
  })
  runtime.offlineResources = config.offline_resources ? structuredClone(config.offline_resources) :
    runtime.offlineResources.map(item => ({ ...item, uri: resources[item.role] || item.uri }))
  evaluation.outputObsUri = config.evaluation.output_obs_uri || ''
  evaluation.dataset = { enabled: Boolean(config.evaluation.datasets.length), source: 'obs',
    names: [...config.evaluation.datasets], obsUri: resources.eval_bundle_obs_uri }
  const strategies = config.strategies.map(item => ({ ...createStrategy(item.type),
    name: item.name, seed: item.seed ?? 42, proxyExperiments: item.proxy_experiments,
    proxySteps: item.proxy_steps, searchCount: item.search_count, devicesPerNode: item.devices_per_node,
    ratios: item.ratios ? { ...item.ratios } : undefined,
    source: item.script_obs_uri ? 'script' : 'builtin', scriptObsUri: item.script_obs_uri || '',
    scriptConfig: structuredClone(item.script_config || {}),
  }))
  return { runtime, training, evaluation, strategies }
}
