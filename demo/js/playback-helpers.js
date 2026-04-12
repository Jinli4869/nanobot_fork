export const DEFAULT_LOG_DELAY = 1200;
export const DEFAULT_ACTION_PREVIEW_DELAY = 900;

export function buildAnimationQueue(agentLog, trajectory, logDelay = DEFAULT_LOG_DELAY) {
  const queue = [];
  const entries = agentLog?.entries || [];
  const steps = trajectory?.steps || [];

  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];

    if (entry.type === 'tool_call' && entry.linkedSteps) {
      queue.push({ type: 'log', idx: i, delay: logDelay });

      const [start, end] = entry.linkedSteps;
      for (let stepIdx = start; stepIdx <= end; stepIdx++) {
        if (stepIdx < steps.length) {
          queue.push({ type: 'step', idx: stepIdx });
        }
      }
      continue;
    }

    queue.push({ type: 'log', idx: i, delay: logDelay });
  }

  return queue;
}

export function deriveJumpState(queue, stepIdx) {
  let visibleLogCount = 0;
  let animationIndex = -1;

  for (let i = 0; i < queue.length; i++) {
    const evt = queue[i];
    if (evt.type === 'step' && evt.idx > stepIdx) {
      break;
    }
    if (evt.type === 'log') {
      visibleLogCount = evt.idx + 1;
      continue;
    }
    if (evt.type === 'step' && evt.idx <= stepIdx) {
      animationIndex = i;
    }
  }

  return {
    visibleLogCount,
    maxRenderedStep: stepIdx,
    animationIndex,
  };
}

export function getStepPhaseDurations(playbackSpeed, previewDelay = DEFAULT_ACTION_PREVIEW_DELAY) {
  const boundedSpeed = Math.max(0, playbackSpeed || 0);
  const safePreview = Math.min(previewDelay, Math.floor(boundedSpeed / 2) || boundedSpeed);

  return {
    previewDelay: safePreview,
    postCommitDelay: Math.max(0, boundedSpeed - safePreview),
  };
}
