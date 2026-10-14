// Materialize defaults once; an edited empty command must remain empty for validation.
export function initializeJobCommands(strategies, runtime, defaults) {
  runtime.commands = { ...defaults, ...runtime.commands }
  for (const strategy of strategies) {
    strategy.mixingCommand ??= runtime.commands.mixing
    strategy.trainingCommand ??= runtime.commands.training
  }
}

export function refreshJobCommands(strategies, runtime, defaults) {
  const previous = runtime.autoCommandDefaults || runtime.commands || {}
  runtime.commands ||= {}
  for (const stage of ['mixing', 'training', 'evaluation']) {
    if (runtime.commands[stage] == null || runtime.commands[stage] === previous[stage]) runtime.commands[stage] = defaults[stage]
    for (const strategy of strategies) {
      if (stage === 'evaluation') continue
      const key = `${stage}Command`
      if (strategy[key] == null || strategy[key] === previous[stage]) strategy[key] = defaults[stage]
    }
  }
  runtime.autoCommandDefaults = { ...defaults }
}

export function validateJobCommands(jobs) {
  for (const job of jobs) {
    const command = job.owner[job.commandKey]
    if (typeof command !== 'string' || !command.trim()) throw new Error(`${job.label}：command 不能为空。`)
    if (command.includes('\0') || command.length > 32768) throw new Error(`${job.label}：command 不能包含空字符或超过 32768 字符。`)
  }
}
