export function createLiveSnapshot() {
  return {
    entries: [],
    steps: [],
    metadata: {
      task: '',
      platform: 'android',
      screen_width: 1080,
      screen_height: 1920,
    },
    result: null,
  };
}

export function reduceLiveEvent(snapshot, event) {
  const next = {
    ...snapshot,
    entries: [...snapshot.entries],
    steps: [...snapshot.steps],
    metadata: { ...snapshot.metadata },
    result: snapshot.result ? { ...snapshot.result } : null,
  };

  if (event.type === 'run_started') {
    next.metadata.task = event.task || '';
    if (event.platform) next.metadata.platform = event.platform;
    next.entries.push({
      type: 'inbound',
      channel: 'demo-live',
      content: event.task || '',
    });
    return next;
  }

  if (event.type === 'tool_call') {
    if (hasDuplicateToolEntry(next.entries, event, 'tool_call')) return next;
    next.entries.push({
      type: 'tool_call',
      tool: event.tool,
      tool_call_id: event.tool_call_id,
      arguments: event.arguments || {},
    });
    return next;
  }

  if (event.type === 'tool_result') {
    if (hasDuplicateToolEntry(next.entries, event, 'tool_result')) return next;
    next.entries.push({
      type: 'tool_result',
      tool: event.tool,
      tool_call_id: event.tool_call_id,
      result: normalizeToolResult(event.result),
    });
    return next;
  }

  if (event.type === 'assistant_progress') {
    const content = event.content || '';
    if (content && !hasAdjacentContent(next.entries, 'outbound', content)) {
      next.entries.push({
        type: 'outbound',
        channel: 'demo-live',
        content,
      });
    }
    return next;
  }

  if (event.type === 'assistant_final' || event.type === 'run_complete') {
    const content = event.content || '';
    if (content && !hasAdjacentContent(next.entries, 'outbound', content)) {
      next.entries.push({
        type: 'outbound',
        channel: 'demo-live',
        content,
      });
    }
    return next;
  }

  if (event.type === 'frame_meta') {
    if (event.width) next.metadata.screen_width = event.width;
    if (event.height) next.metadata.screen_height = event.height;
    if (event.platform) next.metadata.platform = event.platform;
    return next;
  }

  if (event.type === 'gui_step') {
    const stepEvent = event.event || {};
    const observation = stepEvent.observation || {};
    if (observation.screen_width) next.metadata.screen_width = observation.screen_width;
    if (observation.screen_height) next.metadata.screen_height = observation.screen_height;
    if (observation.platform) next.metadata.platform = observation.platform;
    next.steps.push({
      index: stepEvent.step_index ?? next.steps.length,
      screenshot: null,
      action: stepEvent.action || null,
      action_summary: stepEvent.model_output || '',
      model_output: stepEvent.model_output || '',
      phase: stepEvent.phase || 'agent',
    });
    return next;
  }

  if (event.type === 'gui_result') {
    next.result = {
      success: Boolean((event.event || {}).success),
      total_steps: (event.event || {}).total_steps ?? next.steps.length,
      duration_s: (event.event || {}).duration_s ?? 0,
      error: (event.event || {}).error || null,
    };
    return next;
  }

  if (event.type === 'run_error') {
    next.entries.push({
      type: 'tool_result',
      tool: 'live_run',
      result: {
        success: false,
        summary: event.message || 'Live run failed',
      },
    });
    return next;
  }

  return next;
}

function hasDuplicateToolEntry(entries, event, type) {
  if (event.tool_call_id) {
    return entries.some(
      (entry) => entry.type === type && entry.tool_call_id === event.tool_call_id,
    );
  }
  const last = entries.at(-1);
  return Boolean(
    last &&
    last.type === type &&
    last.tool === event.tool &&
    JSON.stringify(last.arguments || last.result || {}) ===
      JSON.stringify(event.arguments || event.result || {}),
  );
}

function hasAdjacentContent(entries, type, content) {
  const last = entries.at(-1);
  return Boolean(last && last.type === type && last.content === content);
}

function normalizeToolResult(result) {
  if (typeof result === 'string') {
    try {
      const parsed = JSON.parse(result);
      return {
        success: Boolean(parsed.success),
        steps_taken: parsed.steps_taken,
        summary: parsed.summary || parsed.error || result,
        trace_path: parsed.trace_path,
      };
    } catch {
      return { success: true, summary: result };
    }
  }
  if (result && typeof result === 'object') {
    return result;
  }
  return { success: true, summary: String(result ?? '') };
}
