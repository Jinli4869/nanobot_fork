import { state } from '../state.js';
import {
  DEFAULT_ACTION_PREVIEW_DELAY,
  deriveJumpState,
  getStepPhaseDurations,
} from '../playback-helpers.js';

let playTimer = null;
const SPEEDS = [2000, 3000, 4000, 6000];
const SPEED_LABELS = ['2s', '3s', '4s', '6s'];
let speedIndex = 2;

export function initTimeline() {
  const container = document.getElementById('timeline');

  const controls = document.createElement('div');
  controls.className = 'timeline-controls';

  const prevBtn = document.createElement('button');
  prevBtn.className = 'timeline-btn';
  prevBtn.innerHTML = '\u25C0';
  prevBtn.title = 'Previous step (Left arrow)';
  prevBtn.onclick = () => goStep(-1);

  const playBtn = document.createElement('button');
  playBtn.className = 'timeline-btn';
  playBtn.innerHTML = '\u25B6';
  playBtn.title = 'Play/Pause (Space)';
  playBtn.onclick = togglePlay;

  const nextBtn = document.createElement('button');
  nextBtn.className = 'timeline-btn';
  nextBtn.innerHTML = '\u25B6';
  nextBtn.title = 'Next step (Right arrow)';
  nextBtn.onclick = () => goStep(1);

  controls.append(prevBtn, playBtn, nextBtn);

  const dotsContainer = document.createElement('div');
  dotsContainer.className = 'timeline-dots';

  const speedBtn = document.createElement('button');
  speedBtn.className = 'speed-btn';
  speedBtn.textContent = SPEED_LABELS[speedIndex];
  speedBtn.title = 'Playback speed';
  speedBtn.onclick = cycleSpeed;

  const info = document.createElement('div');
  info.className = 'timeline-info';

  container.append(controls, dotsContainer, speedBtn, info);

  function renderDots() {
    const traj = state.get('trajectory');
    dotsContainer.innerHTML = '';
    if (!traj) return;

    traj.steps.forEach((step, i) => {
      const dot = document.createElement('div');
      dot.className = 'timeline-dot';
      dot.dataset.index = i;
      if (step.action?.action_type === 'done') dot.classList.add('done');
      dot.onclick = () => {
        state.set('isPlaying', false);
        jumpToStep(i);
      };
      dotsContainer.appendChild(dot);
    });

    updateActiveDot(state.get('currentStep'));
  }

  function updateActiveDot(stepIdx) {
    dotsContainer.querySelectorAll('.timeline-dot').forEach((dot, i) => {
      dot.classList.toggle('active', i === stepIdx);
    });
    const traj = state.get('trajectory');
    if (traj) {
      info.textContent = `Step ${stepIdx} / ${traj.steps.length - 1}`;
    }
  }

  state.on('trajectory', renderDots);
  state.on('currentStep', updateActiveDot);

  state.on('isPlaying', (playing) => {
    playBtn.innerHTML = playing ? '\u23F8' : '\u25B6';
    if (playing) startQueuePlayback();
    else stopPlayback();
  });

  // Keyboard navigation
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); goStep(-1); }
    if (e.key === 'ArrowRight') { e.preventDefault(); goStep(1); }
    if (e.key === ' ') { e.preventDefault(); togglePlay(); }
  });
}

/**
 * Jump to a specific trajectory step via manual navigation.
 * Also ensures all log entries up to this step are visible,
 * and maxRenderedStep covers this step.
 */
function jumpToStep(stepIdx) {
  const queue = state.get('animationQueue');
  const jumpState = deriveJumpState(queue, stepIdx);
  state.set('visibleLogCount', jumpState.visibleLogCount);
  state.set('maxRenderedStep', jumpState.maxRenderedStep);
  state.set('animationIndex', jumpState.animationIndex);
  state.set('pendingActionStep', null);
  state.set('playbackPhase', 'idle');
  state.set('displayedStep', stepIdx);
  state.set('currentStep', stepIdx);
}

function goStep(delta) {
  const traj = state.get('trajectory');
  if (!traj) return;
  state.set('isPlaying', false);
  const current = state.get('currentStep');
  const next = Math.max(0, Math.min(traj.steps.length - 1, current + delta));
  jumpToStep(next);
}

function togglePlay() {
  state.set('isPlaying', !state.get('isPlaying'));
}

/**
 * Process the animation queue sequentially.
 * Each event fires after its delay, then schedules the next.
 */
function startQueuePlayback() {
  stopPlayback();

  const queue = state.get('animationQueue');
  if (!queue || queue.length === 0) {
    state.set('isPlaying', false);
    return;
  }

  let idx = state.get('animationIndex') + 1;

  // If queue was fully played, restart from the beginning
  if (idx >= queue.length) {
    idx = 0;
    state.set('animationIndex', -1);
    state.set('visibleLogCount', 0);
    state.set('maxRenderedStep', -1);
    state.set('currentStep', 0);
    state.set('displayedStep', 0);
    state.set('pendingActionStep', null);
    state.set('playbackPhase', 'idle');
  }

  function processNext() {
    if (!state.get('isPlaying')) return;
    if (idx >= queue.length) {
      state.set('isPlaying', false);
      return;
    }

    const evt = queue[idx];
    if (evt.type === 'log') {
      state.set('visibleLogCount', evt.idx + 1);
      state.set('animationIndex', idx);
      idx++;
      playTimer = setTimeout(processNext, evt.delay || 800);
      return;
    }

    playStepEvent(evt.idx, idx, processNext);
    idx++;
  }

  function playStepEvent(stepIdx, queueIndex, continuePlayback) {
    const traj = state.get('trajectory');
    const step = traj?.steps?.[stepIdx];
    const { previewDelay, postCommitDelay } = getStepPhaseDurations(
      state.get('playbackSpeed'),
      DEFAULT_ACTION_PREVIEW_DELAY,
    );

    const commitStep = () => {
      state.set('pendingActionStep', null);
      state.set('playbackPhase', 'frame-commit');
      state.set('displayedStep', stepIdx);
      state.set('currentStep', stepIdx);
      state.set('maxRenderedStep', Math.max(state.get('maxRenderedStep'), stepIdx));
    };

    state.set('animationIndex', queueIndex);

    if (!step?.action || stepIdx === 0) {
      commitStep();
      playTimer = setTimeout(continuePlayback, state.get('playbackSpeed'));
      return;
    }

    state.set('pendingActionStep', stepIdx);
    state.set('playbackPhase', 'action-preview');

    playTimer = setTimeout(() => {
      if (!state.get('isPlaying')) return;
      commitStep();
      playTimer = setTimeout(continuePlayback, postCommitDelay);
    }, previewDelay);
  }

  processNext();
}

function stopPlayback() {
  if (playTimer) { clearTimeout(playTimer); playTimer = null; }
}

function cycleSpeed() {
  speedIndex = (speedIndex + 1) % SPEEDS.length;
  state.set('playbackSpeed', SPEEDS[speedIndex]);
  const btn = document.querySelector('.speed-btn');
  if (btn) btn.textContent = SPEED_LABELS[speedIndex];
}
