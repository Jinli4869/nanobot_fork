import { state } from '../state.js';

let typewriterTimer = null;

export function initModelOutput() {
  const body = document.querySelector('#model-output .panel-body');

  function render(stepIdx) {
    const traj = state.get('trajectory');
    if (!traj) {
      body.innerHTML = '<div class="empty-state"><div class="icon">\u{1F916}</div>Model reasoning</div>';
      return;
    }

    const step = traj.steps[stepIdx];
    if (!step) return;

    body.innerHTML = '';

    const block = document.createElement('div');
    block.className = 'model-output-step';

    // Step label
    const label = document.createElement('div');
    label.className = 'step-label';
    label.textContent = stepIdx === 0 ? 'Initial State' : `Step ${stepIdx}`;
    block.appendChild(label);

    // Model output text with typewriter effect
    const textEl = document.createElement('div');
    textEl.className = 'model-output-text';
    block.appendChild(textEl);

    const text = step.model_output || step.action_summary || (stepIdx === 0 ? 'Taking initial screenshot...' : '');
    typewriterEffect(textEl, text);

    // Action badge
    if (step.action) {
      const badge = document.createElement('div');
      badge.className = 'action-badge';

      const typeName = document.createElement('span');
      typeName.className = 'action-type';
      typeName.textContent = step.action.action_type;
      badge.appendChild(typeName);

      const details = formatActionDetails(step.action);
      if (details) {
        const detailSpan = document.createElement('span');
        detailSpan.textContent = details;
        badge.appendChild(detailSpan);
      }

      block.appendChild(badge);
    }

    // Observation info
    const obs = document.createElement('div');
    obs.className = 'observation-info';
    const meta = traj.metadata;
    const lines = [];
    lines.push(`Platform: ${meta.platform}`);
    lines.push(`Screen: ${meta.screen_width} x ${meta.screen_height}`);
    if (step.action?.relative) lines.push('Coordinates: relative [0-999]');
    obs.innerHTML = lines.join('<br>');
    block.appendChild(obs);

    body.appendChild(block);
  }

  state.on('currentStep', render);
  state.on('trajectory', () => render(state.get('currentStep')));
}

function typewriterEffect(el, text) {
  if (typewriterTimer) clearInterval(typewriterTimer);

  if (!text) { el.textContent = ''; return; }

  let idx = 0;
  el.innerHTML = '';
  const cursor = document.createElement('span');
  cursor.className = 'cursor';

  typewriterTimer = setInterval(() => {
    if (idx < text.length) {
      el.textContent = text.slice(0, idx + 1);
      el.appendChild(cursor);
      idx++;
    } else {
      clearInterval(typewriterTimer);
      typewriterTimer = null;
      // Remove cursor after a moment
      setTimeout(() => cursor.remove(), 1500);
    }
  }, 20);
}

function formatActionDetails(action) {
  const t = action.action_type;
  if (t === 'tap' || t === 'double_tap' || t === 'long_press') {
    return `(${action.x}, ${action.y})`;
  }
  if (t === 'swipe' || t === 'drag') {
    return `(${action.x},${action.y}) \u2192 (${action.x2},${action.y2})`;
  }
  if (t === 'input_text') return `"${(action.text || '').slice(0, 20)}"`;
  if (t === 'scroll') return action.text || '';
  if (t === 'hotkey') return (action.key || []).join('+');
  if (t === 'open_app' || t === 'close_app') return action.text || '';
  if (t === 'done') return action.status || '';
  return '';
}
