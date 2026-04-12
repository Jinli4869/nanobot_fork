import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildAnimationQueue,
  deriveJumpState,
  getStepPhaseDurations,
} from '../js/playback-helpers.js';

test('buildAnimationQueue expands linked tool calls into step events', () => {
  const agentLog = {
    entries: [
      { type: 'inbound' },
      { type: 'tool_call', linkedSteps: [0, 2] },
      { type: 'tool_result' },
      { type: 'outbound' },
    ],
  };
  const trajectory = { steps: [{}, {}, {}] };

  const queue = buildAnimationQueue(agentLog, trajectory);

  assert.deepEqual(
    queue.map(({ type, idx }) => ({ type, idx })),
    [
      { type: 'log', idx: 0 },
      { type: 'log', idx: 1 },
      { type: 'step', idx: 0 },
      { type: 'step', idx: 1 },
      { type: 'step', idx: 2 },
      { type: 'log', idx: 2 },
      { type: 'log', idx: 3 },
    ],
  );
});

test('deriveJumpState reveals logs through the requested step and resumes after it', () => {
  const queue = [
    { type: 'log', idx: 0 },
    { type: 'log', idx: 1 },
    { type: 'step', idx: 0 },
    { type: 'log', idx: 2 },
    { type: 'step', idx: 1 },
    { type: 'log', idx: 3 },
    { type: 'step', idx: 2 },
    { type: 'log', idx: 4 },
  ];

  const jumpState = deriveJumpState(queue, 1);

  assert.deepEqual(jumpState, {
    visibleLogCount: 4,
    maxRenderedStep: 1,
    animationIndex: 4,
  });
});

test('getStepPhaseDurations keeps a preview pause before the frame commit', () => {
  assert.deepEqual(getStepPhaseDurations(4000, 900), {
    previewDelay: 900,
    postCommitDelay: 3100,
  });

  assert.deepEqual(getStepPhaseDurations(600, 900), {
    previewDelay: 300,
    postCommitDelay: 300,
  });
});
