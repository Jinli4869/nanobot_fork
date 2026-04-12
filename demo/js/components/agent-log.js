import { state } from '../state.js';

export function initAgentLog() {
  const body = document.querySelector('#agent-log .panel-body');

  function render() {
    const log = state.get('agentLog');
    if (!log) {
      body.innerHTML = '<div class="empty-state"><div class="icon">\u{1F4CB}</div>Select a scenario</div>';
      return;
    }

    body.innerHTML = '';
    log.entries.forEach((entry, i) => {
      const el = document.createElement('div');
      el.className = `log-entry ${entry.type}`;
      el.dataset.index = i;

      if (entry.type === 'tool_result' && entry.result && !entry.result.success) {
        el.classList.add('failed');
      }

      const label = document.createElement('div');
      label.className = 'label';

      const content = document.createElement('div');

      switch (entry.type) {
        case 'inbound':
          label.textContent = `\u25B6 User Message`;
          content.textContent = entry.content;
          break;
        case 'tool_call':
          label.textContent = `\u25B6 Tool Call: ${entry.tool}`;
          content.textContent = JSON.stringify(entry.arguments, null, 2);
          break;
        case 'tool_result':
          label.textContent = `\u25C0 Tool Result: ${entry.tool || ''}`;
          const r = entry.result || {};
          content.innerHTML = `<span style="color:${r.success ? 'var(--accent-green)' : 'var(--accent-red)'}">${r.success ? 'Success' : 'Failed'}</span> &mdash; ${r.steps_taken || 0} steps`;
          if (r.summary) content.innerHTML += `<br/>${r.summary}`;
          break;
        case 'outbound':
          label.textContent = `\u25C0 Agent Response`;
          content.textContent = entry.content;
          break;
      }

      el.appendChild(label);
      el.appendChild(content);
      body.appendChild(el);
    });
  }

  state.on('agentLog', render);

  // Highlight linked log entry based on current step
  state.on('currentStep', (stepIdx) => {
    const log = state.get('agentLog');
    if (!log) return;

    body.querySelectorAll('.log-entry').forEach(el => el.classList.remove('highlight'));

    // Find the tool_call entry whose linkedSteps covers current step
    log.entries.forEach((entry, i) => {
      if (entry.type === 'tool_call' && entry.linkedSteps) {
        const [start, end] = entry.linkedSteps;
        if (stepIdx >= start && stepIdx <= end) {
          const el = body.querySelector(`[data-index="${i}"]`);
          if (el) el.classList.add('highlight');
        }
      }
    });
  });
}
