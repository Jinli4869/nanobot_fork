import { state } from '../state.js';

let imgEl = null;
let overlayEl = null;
let containerEl = null;
let frameEl = null;
let badgeEl = null;
let currentScreenshotSrc = null;
let renderedActionKey = null;
let overlayToken = 0;

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
  state.on('trajectory', (traj) => {
    if (!traj) {
      currentScreenshotSrc = null;
      imgEl.removeAttribute('src');
      imgEl.style.opacity = '0';
      clearActionOverlay();
      badgeEl.textContent = '';
      return;
    }
    renderStep(state.get('currentStep'));
  });
  state.on('currentStep', renderStep);
  state.on('displayedStep', renderStep);
  state.on('pendingActionStep', renderStep);
  state.on('playbackPhase', renderStep);
  state.on('isPlaying', renderStep);
  state.on('liveFrameUrl', renderLiveFrame);
  state.on('mode', (mode) => {
    if (mode === 'live' && !state.get('liveFrameUrl')) {
      renderLivePlaceholder();
    }
  });
}

function updateDeviceType() {
  const traj = state.get('trajectory');
  if (!traj?.metadata) return;
  const { screen_width, screen_height } = traj.metadata;
  const isPortrait = screen_height > screen_width;
  const isDesktop = traj.metadata.platform === 'macos' ||
                    traj.metadata.platform === 'windows' ||
                    traj.metadata.platform === 'linux';

  frameEl.className = 'device-frame ' + (isDesktop ? 'desktop' : isPortrait ? 'phone' : 'tablet');
}

function renderStep(stepIdx) {
  const traj = state.get('trajectory');
  if (!traj || !traj.steps.length) {
    const liveUrl = state.get('liveFrameUrl');
    if (state.get('mode') === 'live') {
      if (liveUrl) renderLiveFrame(liveUrl);
      else renderLivePlaceholder();
    }
    return;
  }

  const displayedStepIdx = Math.max(0, Math.min(
    state.get('displayedStep') ?? stepIdx ?? 0,
    traj.steps.length - 1,
  ));
  const displayedStep = traj.steps[displayedStepIdx];
  const previewStepIdx = state.get('pendingActionStep');
  const isPreview = state.get('playbackPhase') === 'action-preview' && previewStepIdx != null;
  const previewStep = isPreview ? traj.steps[previewStepIdx] : null;

  if (state.get('mode') === 'live' && state.get('liveFrameUrl')) {
    renderLiveFrame(state.get('liveFrameUrl'));
    return;
  }

  badgeEl.textContent = isPreview
    ? `Preview Step ${previewStepIdx}/${traj.steps.length - 1}`
    : `Step ${displayedStepIdx}/${traj.steps.length - 1}`;

  // Update screenshot with crossfade
  if (displayedStep?.screenshot && displayedStep.screenshot !== currentScreenshotSrc) {
    const newImg = new Image();
    newImg.src = displayedStep.screenshot;
    newImg.onload = () => {
      imgEl.src = newImg.src;
      currentScreenshotSrc = newImg.src;
      imgEl.style.opacity = '1';
      imgEl.classList.remove('screenshot-enter');
      void imgEl.offsetWidth; // force reflow
      imgEl.classList.add('screenshot-enter');
    };
  } else if (!displayedStep?.screenshot) {
    imgEl.style.opacity = '0.3';
    currentScreenshotSrc = null;
  }

  // Render action overlay
  clearActionOverlay();
  const shouldShowCommittedAction = !state.get('isPlaying') && state.get('currentStep') === displayedStepIdx;
  const actionStep = previewStep || (shouldShowCommittedAction ? displayedStep : null);
  if (actionStep?.action) {
    renderActionOverlay(actionStep.action, traj.metadata, overlayToken);
  }
}

function renderLiveFrame(url) {
  if (state.get('mode') !== 'live') return;
  if (!url) {
    renderLivePlaceholder();
    return;
  }
  updateDeviceType();
  containerEl.classList.remove('live-waiting');
  if (url !== currentScreenshotSrc) {
    imgEl.src = url;
    currentScreenshotSrc = url;
    imgEl.style.opacity = '1';
  }
  const traj = state.get('trajectory');
  const stepIdx = state.get('currentStep') || 0;
  badgeEl.textContent = traj?.steps?.length ? `Live Step ${stepIdx}` : 'Live';
  const step = traj?.steps?.[stepIdx];
  if (step?.action) {
    renderLiveActionOverlay(step.action, traj.metadata, step.index ?? stepIdx);
  } else {
    clearActionOverlay();
  }
}

function renderLivePlaceholder() {
  if (state.get('mode') !== 'live') return;
  updateDeviceType();
  currentScreenshotSrc = null;
  imgEl.removeAttribute('src');
  imgEl.style.opacity = '0';
  clearActionOverlay();
  badgeEl.textContent = 'Waiting for live frame';
  containerEl.classList.add('live-waiting');
}

function clearActionOverlay() {
  overlayToken += 1;
  renderedActionKey = null;
  overlayEl.innerHTML = '';
}

function renderLiveActionOverlay(action, metadata, stepKey) {
  const actionKey = getActionOverlayKey(action, metadata, stepKey);
  if (actionKey === renderedActionKey) {
    return;
  }
  overlayToken += 1;
  renderedActionKey = actionKey;
  overlayEl.innerHTML = '';
  renderActionOverlay(action, metadata, overlayToken);
}

function getActionOverlayKey(action, metadata, stepKey) {
  return JSON.stringify({
    step: stepKey,
    type: action.action_type,
    x: action.x ?? null,
    y: action.y ?? null,
    x2: action.x2 ?? null,
    y2: action.y2 ?? null,
    relative: Boolean(action.relative),
    text: action.text ?? null,
    status: action.status ?? null,
    width: metadata?.screen_width ?? null,
    height: metadata?.screen_height ?? null,
  });
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

function renderActionOverlay(action, metadata, token) {
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
        if (token !== overlayToken) return;
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
