import test from 'node:test';
import assert from 'node:assert/strict';

import { state } from '../js/state.js';
import { initAgentLog } from '../js/components/agent-log.js';

class FakeElement {
  constructor(tagName = 'div') {
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.parent = null;
    this.textContent = '';
    this._innerHTML = '';
    this.className = '';
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.classList = {
      add: (...names) => {
        const current = new Set(String(this.className || '').split(/\s+/).filter(Boolean));
        names.forEach((name) => current.add(name));
        this.className = [...current].join(' ');
      },
    };
  }

  set innerHTML(value) {
    this._innerHTML = value;
    this.children = [];
    if (String(value).includes('empty-state')) {
      const empty = new FakeElement('div');
      empty.className = 'empty-state';
      this.appendChild(empty);
    }
  }

  get innerHTML() {
    return this._innerHTML;
  }

  appendChild(child) {
    child.parent = this;
    this.children.push(child);
    this.scrollHeight = this.children.length;
    return child;
  }

  remove() {
    if (!this.parent) return;
    this.parent.children = this.parent.children.filter((child) => child !== this);
    this.parent = null;
  }

  querySelector(selector) {
    if (selector === '.empty-state') {
      return this.children.find((child) => child.className.includes('empty-state')) || null;
    }
    return null;
  }

  replaceChildren(...children) {
    this.children = [];
    children.forEach((child) => this.appendChild(child));
  }
}

test('agent log rerenders when log object changes without visible count change', () => {
  const body = new FakeElement('div');
  globalThis.document = {
    querySelector: (selector) => (selector === '#agent-log .panel-body' ? body : null),
    createElement: (tagName) => new FakeElement(tagName),
  };

  initAgentLog();

  const entries = [
    { type: 'inbound', channel: 'demo-live', content: 'open settings' },
    { type: 'tool_call', tool: 'gui_task', arguments: { backend: 'scrcpy-adb' } },
  ];

  state.set('visibleLogCount', 0);
  state.set('agentLog', { entries });
  state.set('visibleLogCount', entries.length);
  assert.equal(body.children.length, 2);

  state.set('agentLog', { entries });
  assert.equal(body.children.length, 2);
  assert.equal(body.children[1].dataset.tool, 'gui_task');
});
