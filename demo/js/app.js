import { state } from './state.js';
import { loadManifest, loadScenario } from './data-loader.js';
import { initPlatformTabs } from './components/platform-tabs.js';
import { initScenarioPicker } from './components/scenario-picker.js';
import { initDeviceViewer } from './components/device-viewer.js';
import { initAgentLog } from './components/agent-log.js';
import { initModelOutput } from './components/model-output.js';
import { initTimeline } from './components/timeline.js';

async function init() {
  // Init all components
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

    state.set('isPlaying', false);
    state.set('currentStep', 0);

    try {
      const { trajectory, agentLog } = await loadScenario(platformId, scenarioId);
      state.set('trajectory', trajectory);
      state.set('agentLog', agentLog);
    } catch (e) {
      console.error('Failed to load scenario:', e);
      state.set('trajectory', null);
      state.set('agentLog', null);
    }
  });

  // When platform changes, reset scenario
  state.on('currentPlatform', () => {
    state.set('trajectory', null);
    state.set('agentLog', null);
    state.set('currentStep', 0);
    state.set('currentScenario', null);
  });

  // Load manifest and kick off
  const manifest = await loadManifest();
  state.set('manifest', manifest);
}

init().catch(console.error);
