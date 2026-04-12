/**
 * Simple reactive state store with pub/sub.
 */
class State {
  constructor(initial) {
    this._state = { ...initial };
    this._listeners = new Map();
  }

  get(key) {
    return this._state[key];
  }

  set(key, value) {
    if (this._state[key] === value) return;
    const old = this._state[key];
    this._state[key] = value;
    this._notify(key, value, old);
  }

  on(key, fn) {
    if (!this._listeners.has(key)) this._listeners.set(key, new Set());
    this._listeners.get(key).add(fn);
    return () => this._listeners.get(key)?.delete(fn);
  }

  _notify(key, value, old) {
    this._listeners.get(key)?.forEach(fn => fn(value, old));
    this._listeners.get('*')?.forEach(fn => fn(key, value, old));
  }
}

export const state = new State({
  currentPlatform: null,
  currentScenario: null,
  currentStep: 0,
  isPlaying: false,
  playbackSpeed: 2000, // ms per step
  manifest: null,
  trajectory: null,
  agentLog: null,
});
