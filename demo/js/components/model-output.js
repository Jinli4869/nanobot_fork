import { state } from '../state.js';

let body = null;
let renderedSteps = new Set();
let typewriterTimer = null;

export function initModelOutput() {
  body = document.querySelector('#model-output .panel-body');

  // Clear when a new trajectory loads
  state.on('trajectory', () => {
    clearAll();
  });

  // When maxRenderedStep advances, append new steps
  state.on('maxRenderedStep', (maxStep) => {
    if (maxStep < 0) {
      clearAll();
      return;
    }

    const traj = state.get('trajectory');
    if (!traj) return;

    // Remove empty state if present
    const empty = body.querySelector('.empty-state');
    if (empty) empty.remove();

    // Render all steps up to maxStep that haven't been rendered
    for (let i = 0; i <= maxStep; i++) {
      if (!renderedSteps.has(i) && traj.steps[i]) {
        appendStep(traj.steps[i], i, traj);
        renderedSteps.add(i);
      }
    }
  });

  // Highlight the current step visually
  state.on('currentStep', (stepIdx) => {
    body.querySelectorAll('.model-output-step').forEach(el => {
      const idx = parseInt(el.dataset.stepIndex, 10);
      el.classList.toggle('active-step', idx === stepIdx);
      el.classList.toggle('past-step', idx < stepIdx);
    });

    // Auto-scroll to the active step
    const activeEl = body.querySelector('.model-output-step.active-step');
    if (activeEl) {
      activeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });
}

function clearAll() {
  if (typewriterTimer) {
    clearInterval(typewriterTimer);
    typewriterTimer = null;
  }
  renderedSteps.clear();
  body.innerHTML = '<div class="empty-state"><div class="icon">\u{1F916}</div>Model reasoning</div>';
  body.scrollTop = 0;
}

function appendStep(step, stepIdx) {
  const block = document.createElement('div');
  block.className = 'model-output-step slide-in';
  block.dataset.stepIndex = stepIdx;

  // Step label
  const label = document.createElement('div');
  label.className = 'step-label';
  label.textContent = stepIdx === 0 ? 'Initial State' : `Step ${stepIdx}`;
  block.appendChild(label);

  // Model output text
  const textEl = document.createElement('div');
  textEl.className = 'model-output-text';
  const text = step.model_output || step.action_summary || (stepIdx === 0 ? 'Taking initial screenshot...' : '');
  textEl.textContent = text;
  block.appendChild(textEl);

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

  body.appendChild(block);

  // Auto-scroll to bottom
  body.scrollTop = body.scrollHeight;
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
