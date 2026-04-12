import { state } from '../state.js';

let imgEl = null;
let overlayEl = null;
let containerEl = null;
let frameEl = null;
let badgeEl = null;

export function initDeviceViewer() {
  const panel = document.querySelector('#device-viewer .panel-body');
  frameEl = document.createElement('div');
  frameEl.className = 'device-frame phone';

  containerEl = document.createElement('div');
  containerEl.className = 'screenshot-container';

  imgEl = document.createElement('img');
  imgEl.alt = 'Device screenshot';
  imgEl.style.opacity = '0';

  overlayEl = document.createElement('div');
  overlayEl.className = 'action-overlay';

  badgeEl = document.createElement('div');
  badgeEl.className = 'step-badge';

  containerEl.appendChild(imgEl);
  containerEl.appendChild(overlayEl);
  containerEl.appendChild(badgeEl);
  frameEl.appendChild(containerEl);
  panel.appendChild(frameEl);

  state.on('trajectory', updateDeviceType);
  state.on('currentStep', renderStep);
  state.on('trajectory', () => renderStep(state.get('currentStep')));
}

function updateDeviceType() {
  const traj = state.get('trajectory');
  if (!traj) return;
  const { screen_width, screen_height } = traj.metadata;
  const isPortrait = screen_height > screen_width;
  const isDesktop = traj.metadata.platform === 'macos' ||
                    traj.metadata.platform === 'windows' ||
                    traj.metadata.platform === 'linux';

  frameEl.className = 'device-frame ' + (isDesktop ? 'desktop' : isPortrait ? 'phone' : 'tablet');
}

function renderStep(stepIdx) {
  const traj = state.get('trajectory');
  if (!traj || !traj.steps[stepIdx]) return;

  const step = traj.steps[stepIdx];
  badgeEl.textContent = `Step ${stepIdx}/${traj.steps.length - 1}`;

  // Update screenshot with crossfade
  if (step.screenshot) {
    const newImg = new Image();
    newImg.src = step.screenshot;
    newImg.onload = () => {
      imgEl.src = newImg.src;
      imgEl.style.opacity = '1';
      imgEl.classList.remove('screenshot-enter');
      void imgEl.offsetWidth; // force reflow
      imgEl.classList.add('screenshot-enter');
    };
  } else {
    imgEl.style.opacity = '0.3';
  }

  // Render action overlay
  overlayEl.innerHTML = '';
  if (step.action) {
    renderActionOverlay(step.action, traj.metadata);
  }
}

function getPosition(action, metadata) {
  let fracX = 0, fracY = 0;
  if (action.relative) {
    fracX = (action.x || 0) / 999;
    fracY = (action.y || 0) / 999;
  } else {
    fracX = (action.x || 0) / (metadata.screen_width || 1);
    fracY = (action.y || 0) / (metadata.screen_height || 1);
  }
  return { x: fracX * 100, y: fracY * 100 };
}

function getPosition2(action, metadata) {
  let fracX = 0, fracY = 0;
  if (action.relative) {
    fracX = (action.x2 || 0) / 999;
    fracY = (action.y2 || 0) / 999;
  } else {
    fracX = (action.x2 || 0) / (metadata.screen_width || 1);
    fracY = (action.y2 || 0) / (metadata.screen_height || 1);
  }
  return { x: fracX * 100, y: fracY * 100 };
}

function renderActionOverlay(action, metadata) {
  const type = action.action_type;

  if (type === 'tap' || type === 'double_tap') {
    const pos = getPosition(action, metadata);
    const ripple = document.createElement('div');
    ripple.className = 'tap-ripple';
    ripple.style.left = pos.x + '%';
    ripple.style.top = pos.y + '%';
    overlayEl.appendChild(ripple);
    if (type === 'double_tap') {
      setTimeout(() => {
        const r2 = document.createElement('div');
        r2.className = 'tap-ripple';
        r2.style.left = pos.x + '%';
        r2.style.top = pos.y + '%';
        overlayEl.appendChild(r2);
      }, 200);
    }
  }

  else if (type === 'long_press') {
    const pos = getPosition(action, metadata);
    const ripple = document.createElement('div');
    ripple.className = 'long-press-ripple';
    ripple.style.left = pos.x + '%';
    ripple.style.top = pos.y + '%';
    overlayEl.appendChild(ripple);
  }

  else if (type === 'swipe' || type === 'drag') {
    const p1 = getPosition(action, metadata);
    const p2 = getPosition2(action, metadata);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 100 100');
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;';

    // Line
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', p1.x);
    line.setAttribute('y1', p1.y);
    line.setAttribute('x2', p2.x);
    line.setAttribute('y2', p2.y);
    line.classList.add('swipe-line');

    // Start dot
    const dot1 = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    dot1.setAttribute('cx', p1.x);
    dot1.setAttribute('cy', p1.y);
    dot1.classList.add('swipe-dot-start');

    // End dot
    const dot2 = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    dot2.setAttribute('cx', p2.x);
    dot2.setAttribute('cy', p2.y);
    dot2.classList.add('swipe-dot-end');

    // Arrowhead
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    const angle = Math.atan2(dy, dx);
    const arrowSize = 2;
    const ax1 = p2.x - arrowSize * Math.cos(angle - 0.5);
    const ay1 = p2.y - arrowSize * Math.sin(angle - 0.5);
    const ax2 = p2.x - arrowSize * Math.cos(angle + 0.5);
    const ay2 = p2.y - arrowSize * Math.sin(angle + 0.5);
    const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    arrow.setAttribute('points', `${p2.x},${p2.y} ${ax1},${ay1} ${ax2},${ay2}`);
    arrow.classList.add('swipe-arrow');

    svg.append(line, dot1, dot2, arrow);
    overlayEl.appendChild(svg);
  }

  else if (type === 'scroll') {
    const pos = action.x != null ? getPosition(action, metadata) : { x: 50, y: 50 };
    const dir = (action.text || 'down').toLowerCase();
    const indicator = document.createElement('div');
    indicator.className = 'scroll-indicator';
    indicator.style.left = pos.x + '%';
    indicator.style.top = pos.y + '%';

    for (let i = 0; i < 3; i++) {
      const arrow = document.createElement('div');
      arrow.className = 'scroll-arrow ' + dir;
      indicator.appendChild(arrow);
    }
    overlayEl.appendChild(indicator);
  }

  else if (type === 'input_text') {
    const pos = action.x != null ? getPosition(action, metadata) : { x: 50, y: 50 };
    const el = document.createElement('div');
    el.className = 'input-indicator';
    el.style.left = pos.x + '%';
    el.style.top = pos.y + '%';
    el.textContent = action.text ? `"${action.text.slice(0, 30)}"` : 'typing...';
    overlayEl.appendChild(el);
  }

  else if (type === 'done') {
    const el = document.createElement('div');
    el.className = 'done-overlay ' + (action.status === 'success' ? 'success' : 'failure');
    el.textContent = action.status === 'success' ? '\u2713' : '\u2717';
    overlayEl.appendChild(el);
  }
}
