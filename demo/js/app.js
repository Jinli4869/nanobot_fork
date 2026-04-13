import { state } from './state.js';
import { loadManifest, loadScenario } from './data-loader.js';
import { initPlatformTabs } from './components/platform-tabs.js';
import { initScenarioPicker } from './components/scenario-picker.js';
import { initDeviceViewer } from './components/device-viewer.js';
import { initAgentLog } from './components/agent-log.js';
import { initModelOutput } from './components/model-output.js';
import { initTimeline } from './components/timeline.js';
import { buildAnimationQueue } from './playback-helpers.js';

function initFullscreenMode() {
  const app = document.getElementById('app');
  const toggle = document.getElementById('fullscreen-toggle');

  if (!app || !toggle) return;

  async function toggleFullscreen() {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
      return;
    }
    await app.requestFullscreen();
  }

  function syncFullscreenUi() {
    const active = document.fullscreenElement === app;
    app.classList.toggle('recording-mode', active);
    toggle.textContent = active ? 'Exit Fullscreen' : 'Fullscreen';
    toggle.setAttribute(
      'title',
      active ? 'Exit fullscreen recording mode (F)' : 'Toggle fullscreen recording mode (F)',
    );
  }

  toggle.addEventListener('click', () => {
    toggleFullscreen().catch((error) => {
      console.error('Failed to toggle fullscreen mode:', error);
    });
  });

  document.addEventListener('fullscreenchange', syncFullscreenUi);
  document.addEventListener('keydown', (event) => {
    if (event.key.toLowerCase() !== 'f') return;
    if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') return;
    event.preventDefault();
    toggleFullscreen().catch((error) => {
      console.error('Failed to toggle fullscreen mode:', error);
    });
  });

  syncFullscreenUi();
}

function resetPlaybackState() {
  state.set('isPlaying', false);
  state.set('currentStep', 0);
  state.set('displayedStep', 0);
  state.set('pendingActionStep', null);
  state.set('playbackPhase', 'idle');
  state.set('visibleLogCount', 0);
  state.set('maxRenderedStep', -1);
  state.set('animationIndex', -1);
}

async function init() {
  // Init all components
  initFullscreenMode();
  initPlatformTabs();
  initScenarioPicker();
  initDeviceViewer();
  initAgentLog();
  initModelOutput();
  initTimeline();

  // When scenario changes, load its data
  state.on('currentScenario', async (scenarioId) => {
    const platformId = state.get('currentPlatform');
    if (!platformId || !scenarioId) return;

    resetPlaybackState();

    try {
      const { trajectory, agentLog } = await loadScenario(platformId, scenarioId);
      state.set('trajectory', trajectory);
      state.set('agentLog', agentLog);
      state.set('animationQueue', buildAnimationQueue(agentLog, trajectory));
    } catch (e) {
      console.error('Failed to load scenario:', e);
      state.set('trajectory', null);
      state.set('agentLog', null);
      state.set('animationQueue', []);
    }
  });

  // When platform changes, reset scenario
  state.on('currentPlatform', () => {
    state.set('trajectory', null);
    state.set('agentLog', null);
    resetPlaybackState();
    state.set('currentScenario', null);
    state.set('animationQueue', []);
  });

  // Load manifest and kick off
  const manifest = await loadManifest();
  state.set('manifest', manifest);
}

init().catch(console.error);
