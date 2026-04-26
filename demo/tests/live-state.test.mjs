import assert from 'node:assert/strict';
import test from 'node:test';

import { createLiveSnapshot, reduceLiveEvent } from '../js/live-state.js';
import { buildAnimationQueue } from '../js/playback-helpers.js';

test('live reducer appends tool calls and gui steps', () => {
  let snapshot = createLiveSnapshot();
  snapshot = reduceLiveEvent(snapshot, { type: 'run_started', task: 'open settings' });
  snapshot = reduceLiveEvent(snapshot, {
    type: 'tool_call',
    tool: 'gui_task',
    arguments: { task: 'open settings' },
  });
  snapshot = reduceLiveEvent(snapshot, {
    type: 'gui_step',
    event: {
      step_index: 0,
      action: { action_type: 'tap', x: 10, y: 20, relative: true },
      model_output: 'tap settings',
      observation: { screen_width: 320, screen_height: 640, platform: 'android' },
    },
  });

  assert.equal(snapshot.entries.length, 2);
  assert.equal(snapshot.entries[1].type, 'tool_call');
  assert.equal(snapshot.steps.length, 1);
  assert.equal(snapshot.steps[0].action.action_type, 'tap');
  assert.equal(snapshot.metadata.screen_width, 320);
});

test('live reducer normalizes gui task json result', () => {
  let snapshot = createLiveSnapshot();
  snapshot = reduceLiveEvent(snapshot, {
    type: 'tool_result',
    tool: 'gui_task',
    result: '{"success": true, "summary": "finished", "steps_taken": 2}',
  });

  assert.equal(snapshot.entries[0].result.success, true);
  assert.equal(snapshot.entries[0].result.steps_taken, 2);
  assert.equal(snapshot.entries[0].result.summary, 'finished');
});

test('live reducer records platform from run and frame metadata', () => {
  let snapshot = createLiveSnapshot();
  snapshot = reduceLiveEvent(snapshot, { type: 'run_started', task: 'open notes', platform: 'ios' });
  snapshot = reduceLiveEvent(snapshot, {
    type: 'frame_meta',
    platform: 'ios',
    width: 390,
    height: 844,
  });

  assert.equal(snapshot.metadata.platform, 'ios');
  assert.equal(snapshot.metadata.screen_width, 390);
  assert.equal(snapshot.metadata.screen_height, 844);
});

test('live reducer drops duplicate tool calls and progress chunks', () => {
  let snapshot = createLiveSnapshot();
  const call = {
    type: 'tool_call',
    tool: 'gui_task',
    tool_call_id: 'call-1',
    arguments: { task: 'open settings', backend: 'adb' },
  };

  snapshot = reduceLiveEvent(snapshot, call);
  snapshot = reduceLiveEvent(snapshot, call);
  snapshot = reduceLiveEvent(snapshot, { type: 'assistant_progress', content: 'Working' });
  snapshot = reduceLiveEvent(snapshot, { type: 'assistant_progress', content: 'Working' });

  assert.equal(snapshot.entries.length, 2);
  assert.equal(snapshot.entries[0].type, 'tool_call');
  assert.equal(snapshot.entries[0].tool_call_id, 'call-1');
  assert.equal(snapshot.entries[1].content, 'Working');
});

test('static playback helper still builds linked step queue', () => {
  const queue = buildAnimationQueue(
    { entries: [{ type: 'tool_call', linkedSteps: [0, 1] }] },
    { steps: [{}, {}] },
  );

  assert.deepEqual(queue.map((item) => item.type), ['log', 'step', 'step']);
});
