import test from 'node:test';
import assert from 'node:assert/strict';

import { state } from '../js/state.js';
import { initDeviceViewer } from '../js/components/device-viewer.js';

class FakeElement {
  constructor(tagName = 'div') {
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.parent = null;
    this.textContent = '';
    this.style = {};
    this.className = '';
    this.appendCount = 0;
    this.classList = {
      add: (...names) => {
        const current = new Set(String(this.className || '').split(/\s+/).filter(Boolean));
        names.forEach((name) => current.add(name));
        this.className = [...current].join(' ');
      },
      remove: (...names) => {
        const removeSet = new Set(names);
        this.className = String(this.className || '')
          .split(/\s+/)
          .filter((name) => name && !removeSet.has(name))
          .join(' ');
      },
    };
  }

  set innerHTML(_value) {
    this.children = [];
  }

  appendChild(child) {
    child.parent = this;
    this.children.push(child);
    this.appendCount += 1;
    return child;
  }

  append(...children) {
    children.forEach((child) => this.appendChild(child));
  }

  setAttribute(name, value) {
    this[name] = value;
  }

  removeAttribute(name) {
    delete this[name];
  }
}

test('live video frames do not replay the same action overlay', () => {
  const panel = new FakeElement('div');
  globalThis.document = {
    querySelector: (selector) => (selector === '#device-viewer .panel-body' ? panel : null),
    createElement: (tagName) => new FakeElement(tagName),
    createElementNS: (_namespace, tagName) => new FakeElement(tagName),
  };

  initDeviceViewer();

  state.set('mode', 'live');
  state.set('liveFrameUrl', 'blob:frame-1');
  state.set('trajectory', {
    metadata: { screen_width: 100, screen_height: 200, platform: 'android' },
    steps: [
      { index: 0, action: { action_type: 'tap', x: 25, y: 50, relative: false } },
    ],
  });

  const overlay = panel.children[0].children[0].children[1];
  assert.equal(overlay.className, 'action-overlay');
  assert.equal(overlay.appendCount, 1);

  state.set('liveFrameUrl', 'blob:frame-2');
  state.set('liveFrameUrl', 'blob:frame-3');
  assert.equal(overlay.appendCount, 1);

  state.set('trajectory', {
    metadata: { screen_width: 100, screen_height: 200, platform: 'android' },
    steps: [
      { index: 0, action: { action_type: 'tap', x: 25, y: 50, relative: false } },
      { index: 1, action: { action_type: 'tap', x: 25, y: 50, relative: false } },
    ],
  });
  state.set('currentStep', 1);
  assert.equal(overlay.appendCount, 2);
});
