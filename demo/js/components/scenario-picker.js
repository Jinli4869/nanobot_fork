import { state } from '../state.js';

export function initScenarioPicker() {
  const container = document.getElementById('scenario-picker');

  function render() {
    const manifest = state.get('manifest');
    const platformId = state.get('currentPlatform');
    if (!manifest || !platformId) return;

    const platform = manifest.platforms.find(p => p.id === platformId);
    if (!platform) { container.innerHTML = ''; return; }

    container.innerHTML = '';
    platform.scenarios.forEach(sc => {
      const card = document.createElement('div');
      card.className = 'scenario-card';
      card.dataset.id = sc.id;
      card.innerHTML = `
        <div class="title">${sc.title}</div>
        <div class="meta">
          <span class="badge ${sc.success ? 'success' : 'failure'}">${sc.success ? '\u2713' : '\u2717'}</span>
          <span>${sc.stepCount} steps</span>
          <span>${sc.duration_s > 0 ? sc.duration_s + 's' : ''}</span>
        </div>
      `;
      card.onclick = () => state.set('currentScenario', sc.id);
      container.appendChild(card);
    });

    // Auto-select first scenario
    if (platform.scenarios.length) {
      const current = state.get('currentScenario');
      if (!current || !platform.scenarios.find(s => s.id === current)) {
        state.set('currentScenario', platform.scenarios[0].id);
      }
    }
  }

  state.on('manifest', render);
  state.on('currentPlatform', render);

  state.on('currentScenario', (id) => {
    container.querySelectorAll('.scenario-card').forEach(card => {
      card.classList.toggle('active', card.dataset.id === id);
    });
  });
}
