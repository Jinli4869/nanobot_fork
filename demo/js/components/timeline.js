import { state } from '../state.js';

let playTimer = null;

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
  speedBtn.textContent = '2s';
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
        state.set('currentStep', i);
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
    if (playing) startPlayback();
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

function goStep(delta) {
  const traj = state.get('trajectory');
  if (!traj) return;
  const current = state.get('currentStep');
  const next = Math.max(0, Math.min(traj.steps.length - 1, current + delta));
  state.set('currentStep', next);
}

function togglePlay() {
  state.set('isPlaying', !state.get('isPlaying'));
}

function startPlayback() {
  stopPlayback();
  playTimer = setInterval(() => {
    const traj = state.get('trajectory');
    if (!traj) { state.set('isPlaying', false); return; }
    const current = state.get('currentStep');
    if (current >= traj.steps.length - 1) {
      state.set('isPlaying', false);
      return;
    }
    state.set('currentStep', current + 1);
  }, state.get('playbackSpeed'));
}

function stopPlayback() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
}

const SPEEDS = [1000, 2000, 3000, 5000];
const SPEED_LABELS = ['1s', '2s', '3s', '5s'];
let speedIndex = 1;

function cycleSpeed() {
  speedIndex = (speedIndex + 1) % SPEEDS.length;
  state.set('playbackSpeed', SPEEDS[speedIndex]);
  const btn = document.querySelector('.speed-btn');
  if (btn) btn.textContent = SPEED_LABELS[speedIndex];
  // Restart playback if playing
  if (state.get('isPlaying')) {
    stopPlayback();
    startPlayback();
  }
}
