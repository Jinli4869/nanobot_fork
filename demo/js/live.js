import { state } from './state.js';
import { createLiveSnapshot, reduceLiveEvent } from './live-state.js';

let snapshot = createLiveSnapshot();
let socket = null;
let previewSocket = null;
let currentRunId = null;
let liveFrameUrl = null;

export function initLiveDemo() {
  const app = document.getElementById('app');
  const platformSelect = document.getElementById('live-platform-select');
  const deviceSelect = document.getElementById('live-device-select');
  const backendSelect = document.getElementById('live-gui-backend');
  const streamLabel = document.querySelector('.live-stream-label');
  const refreshBtn = document.getElementById('live-refresh');
  const taskInput = document.getElementById('live-task');
  const runBtn = document.getElementById('live-run');
  const stopBtn = document.getElementById('live-stop');
  const statusEl = document.getElementById('live-status');

  if (!app || !platformSelect || !deviceSelect || !backendSelect || !streamLabel || !refreshBtn || !taskInput || !runBtn || !stopBtn || !statusEl) {
    return;
  }

  const setStatus = (text, tone = '') => {
    statusEl.textContent = text;
    statusEl.dataset.tone = tone;
    state.set('liveStatus', text);
  };

  function configurePlatform() {
    const platform = platformSelect.value || 'android';
    stopPreview();
    backendSelect.innerHTML = '';
    deviceSelect.innerHTML = '';

    if (platform === 'ios') {
      const backendOption = document.createElement('option');
      backendOption.value = 'ios';
      backendOption.textContent = 'ios';
      backendSelect.appendChild(backendOption);
      backendSelect.value = 'ios';

      const deviceOption = document.createElement('option');
      deviceOption.value = '';
      deviceOption.textContent = 'WDA MJPEG configured';
      deviceSelect.appendChild(deviceOption);
      deviceSelect.disabled = true;
      refreshBtn.disabled = false;
      streamLabel.textContent = 'Video: iOS MJPEG';
      resetLiveState('Live iOS preview', { platform: 'ios' });
      startPreview({ platform: 'ios', serial: null }, setStatus);
      setStatus('Previewing', 'ready');
      return;
    }

    for (const [value, label] of [['adb', 'adb'], ['scrcpy-adb', 'scrcpy-adb']]) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      backendSelect.appendChild(option);
    }
    backendSelect.value = 'adb';
    deviceSelect.disabled = false;
    refreshBtn.disabled = false;
    streamLabel.textContent = 'Video: scrcpy';
    refreshDevices();
  }

  async function refreshDevices() {
    if ((platformSelect.value || 'android') === 'ios') {
      configurePlatform();
      return;
    }
    setStatus('Scanning devices');
    try {
      const resp = await fetch('/api/live/devices');
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      deviceSelect.innerHTML = '';
      for (const device of data.devices || []) {
        const option = document.createElement('option');
        option.value = device.serial;
        option.textContent = `${device.serial} · ${device.state}`;
        option.disabled = device.state !== 'device';
        deviceSelect.appendChild(option);
      }
      if (!deviceSelect.children.length) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'No Android device';
        deviceSelect.appendChild(option);
        stopPreview();
      } else {
        startPreview({ platform: 'android', serial: deviceSelect.value }, setStatus);
      }
      setStatus('Ready', 'ready');
    } catch (error) {
      setStatus(`Device scan failed: ${error.message}`, 'error');
    }
  }

  async function startRun() {
    const task = taskInput.value.trim();
    if (!task) {
      setStatus('Enter a task first', 'error');
      return;
    }
    const platform = platformSelect.value || 'android';
    resetLiveState(task, { keepFrame: true, platform });
    app.classList.add('live-mode');
    setStatus('Starting live run');
    try {
      const resp = await fetch('/api/live/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task,
          platform,
          serial: platform === 'android' ? (deviceSelect.value || null) : null,
          gui_backend: backendSelect.value || 'adb',
        }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      currentRunId = data.run_id;
      connectEvents(currentRunId, setStatus);
      runBtn.disabled = true;
      stopBtn.disabled = false;
      setStatus('Running', 'running');
    } catch (error) {
      setStatus(`Run failed: ${error.message}`, 'error');
      runBtn.disabled = false;
      stopBtn.disabled = true;
    }
  }

  async function stopRun() {
    if (!currentRunId) return;
    const runId = currentRunId;
    currentRunId = null;
    if (socket) socket.close();
    await fetch(`/api/live/runs/${runId}`, { method: 'DELETE' }).catch(() => {});
    runBtn.disabled = false;
    stopBtn.disabled = true;
    setStatus('Stopped', 'error');
  }

  platformSelect.addEventListener('change', configurePlatform);
  refreshBtn.addEventListener('click', refreshDevices);
  deviceSelect.addEventListener('change', () => (
    startPreview({ platform: 'android', serial: deviceSelect.value }, setStatus)
  ));
  runBtn.addEventListener('click', startRun);
  stopBtn.addEventListener('click', stopRun);
  stopBtn.disabled = true;
  configurePlatform();
}

function resetLiveState(task, options = {}) {
  snapshot = createLiveSnapshot();
  snapshot.metadata.task = task;
  snapshot.metadata.platform = options.platform || snapshot.metadata.platform;
  state.set('mode', 'live');
  state.set('isPlaying', false);
  if (!options.keepFrame) {
    if (liveFrameUrl) URL.revokeObjectURL(liveFrameUrl);
    liveFrameUrl = null;
    state.set('liveFrameUrl', null);
  }
  state.set('currentPlatform', options.platform || 'android');
  state.set('currentScenario', null);
  state.set('agentLog', { entries: [] });
  state.set('trajectory', {
    metadata: snapshot.metadata,
    steps: [],
    result: null,
  });
  state.set('visibleLogCount', 0);
  state.set('maxRenderedStep', -1);
  state.set('currentStep', 0);
  state.set('displayedStep', 0);
  state.set('pendingActionStep', null);
  state.set('playbackPhase', 'idle');
}

function startPreview({ platform, serial }, setStatus) {
  if (currentRunId) return;
  if (platform === 'android' && !serial) return;
  stopPreview();
  resetLiveState(
    platform === 'ios' ? 'Live iOS preview' : 'Live Android preview',
    { platform },
  );
  document.getElementById('app')?.classList.add('live-mode');
  setStatus('Previewing', 'ready');

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const source = platform === 'ios' ? 'ios-mjpeg' : 'android-scrcpy';
  const params = new URLSearchParams({ source });
  if (platform === 'android' && serial) params.set('serial', serial);
  previewSocket = new WebSocket(
    `${protocol}//${window.location.host}/api/live/frames?${params.toString()}`,
  );
  previewSocket.binaryType = 'blob';

  previewSocket.onmessage = (message) => {
    if (message.data instanceof Blob) {
      updateLiveFrame(message.data);
      return;
    }
    const event = JSON.parse(message.data);
    if (event.type === 'frame_meta') {
      applyLiveEvent(event);
    } else if (event.type === 'run_error') {
      setStatus(event.message || 'Preview error', 'error');
    }
  };

  previewSocket.onclose = () => {
    if (!currentRunId && state.get('mode') === 'live') {
      setStatus('Preview disconnected', 'error');
    }
  };
}

function stopPreview() {
  if (!previewSocket) return;
  const socketToClose = previewSocket;
  previewSocket = null;
  socketToClose.onclose = null;
  socketToClose.close();
}

function connectEvents(runId, setStatus) {
  if (socket) socket.close();
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(`${protocol}//${window.location.host}/api/live/runs/${runId}/events`);
  socket.binaryType = 'blob';

  socket.onmessage = (message) => {
    if (message.data instanceof Blob) {
      return;
    }
    const event = JSON.parse(message.data);
    applyLiveEvent(event);
    if (event.type === 'run_complete') {
      currentRunId = null;
      setStatus('Complete', 'ready');
      document.getElementById('live-run').disabled = false;
      document.getElementById('live-stop').disabled = true;
    } else if (event.type === 'run_error') {
      currentRunId = null;
      setStatus(event.message || 'Run error', 'error');
      document.getElementById('live-run').disabled = false;
      document.getElementById('live-stop').disabled = true;
    }
  };

  socket.onclose = () => {
    if (currentRunId === runId) {
      setStatus('Disconnected', 'error');
      document.getElementById('live-run').disabled = false;
      document.getElementById('live-stop').disabled = true;
    }
  };
}

function updateLiveFrame(blob) {
  if (liveFrameUrl) URL.revokeObjectURL(liveFrameUrl);
  liveFrameUrl = URL.createObjectURL(blob);
  state.set('liveFrameUrl', liveFrameUrl);
}

function applyLiveEvent(event) {
  const previousEntryCount = snapshot.entries.length;
  const previousStepCount = snapshot.steps.length;
  const previousWidth = snapshot.metadata.screen_width;
  const previousHeight = snapshot.metadata.screen_height;
  const previousPlatform = snapshot.metadata.platform;
  snapshot = reduceLiveEvent(snapshot, event);
  if (snapshot.entries.length !== previousEntryCount) {
    state.set('agentLog', { entries: snapshot.entries });
    state.set('visibleLogCount', snapshot.entries.length);
  }
  const trajectoryChanged =
    snapshot.steps.length !== previousStepCount ||
    snapshot.metadata.screen_width !== previousWidth ||
    snapshot.metadata.screen_height !== previousHeight ||
    snapshot.metadata.platform !== previousPlatform ||
    event.type === 'gui_result';
  if (trajectoryChanged) {
    state.set('trajectory', {
      metadata: snapshot.metadata,
      steps: snapshot.steps,
      result: snapshot.result,
    });
  }
  const lastStep = Math.max(0, snapshot.steps.length - 1);
  state.set('maxRenderedStep', snapshot.steps.length ? lastStep : -1);
  state.set('displayedStep', lastStep);
  state.set('currentStep', lastStep);
  state.set('playbackPhase', 'idle');
}
