import test from 'node:test';
import assert from 'node:assert/strict';

import { initLiveDemo } from '../js/live.js';

class FakeElement {
  constructor(tagName = 'div', id = '') {
    this.tagName = tagName;
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.listeners = new Map();
    this.disabled = false;
    this.textContent = '';
    this.value = '';
    this._innerHTML = '';
    this.classList = { add: () => {} };
  }

  set innerHTML(value) {
    this._innerHTML = value;
    this.children = [];
    if (this.tagName === 'select') this.value = '';
  }

  get innerHTML() {
    return this._innerHTML;
  }

  appendChild(child) {
    this.children.push(child);
    if (this.tagName === 'select' && !this.value) this.value = child.value || '';
    return child;
  }

  addEventListener(event, fn) {
    if (!this.listeners.has(event)) this.listeners.set(event, []);
    this.listeners.get(event).push(fn);
  }

  dispatch(event) {
    for (const fn of this.listeners.get(event) || []) fn();
  }
}

class FakeWebSocket {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.closed = false;
    this.binaryType = '';
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.closed = true;
    this.onclose?.();
  }
}

test('live platform switch closes android preview and starts iOS MJPEG preview', async () => {
  const ids = new Map();
  for (const id of [
    'app',
    'live-platform-select',
    'live-device-select',
    'live-gui-backend',
    'live-refresh',
    'live-task',
    'live-run',
    'live-stop',
    'live-status',
  ]) {
    const tag = id.includes('select') || id.includes('backend') ? 'select' : 'div';
    ids.set(id, new FakeElement(tag, id));
  }
  ids.get('live-platform-select').value = 'android';
  ids.get('live-task').value = 'Open Settings';
  const streamLabel = new FakeElement('span');
  const posts = [];

  globalThis.document = {
    getElementById: (id) => ids.get(id) || null,
    querySelector: (selector) => (selector === '.live-stream-label' ? streamLabel : null),
    createElement: (tagName) => new FakeElement(tagName),
  };
  globalThis.window = {
    location: { protocol: 'http:', host: '127.0.0.1:18880' },
  };
  globalThis.WebSocket = FakeWebSocket;
  globalThis.fetch = async (url, options = {}) => {
    if (url === '/api/live/devices') {
      return {
        ok: true,
        json: async () => ({ devices: [{ serial: 'android-1', state: 'device' }] }),
      };
    }
    if (url === '/api/live/runs') {
      posts.push(JSON.parse(options.body));
      return { ok: true, json: async () => ({ run_id: 'run-1' }) };
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  initLiveDemo();
  await tick();

  assert.equal(FakeWebSocket.instances.length, 1);
  assert.match(FakeWebSocket.instances[0].url, /source=android-scrcpy/);
  assert.match(FakeWebSocket.instances[0].url, /serial=android-1/);

  ids.get('live-platform-select').value = 'ios';
  ids.get('live-platform-select').dispatch('change');

  assert.equal(FakeWebSocket.instances[0].closed, true);
  assert.equal(FakeWebSocket.instances.length, 2);
  assert.match(FakeWebSocket.instances[1].url, /source=ios-mjpeg/);
  assert.equal(ids.get('live-device-select').disabled, true);
  assert.equal(ids.get('live-gui-backend').value, 'ios');
  assert.equal(streamLabel.textContent, 'Video: iOS MJPEG');

  ids.get('live-run').dispatch('click');
  await tick();

  assert.deepEqual(posts[0], {
    task: 'Open Settings',
    platform: 'ios',
    serial: null,
    gui_backend: 'ios',
  });
});

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}
