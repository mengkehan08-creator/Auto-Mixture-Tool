import { trainingParameters } from './data/defaults.js'

export function syncSharedTraining(strategies, config) {
  for (const strategy of strategies) {
    strategy.trainingOverrides = trainingParameters(config)
    strategy.trainingFrameworkSource = config.frameworkSource
    strategy.trainingFrameworkObsUri = config.frameworkSource === 'obs' ? config.frameworkObsUri : ''
    strategy.trainingNodes = strategy.trainingNodesOverride ?? config.nodes
    strategy.trainingPriority = config.priority
    strategy.trainingJobName = ''
    strategy.modelName = ''
  }
}
