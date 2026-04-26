import { state } from '../state.js';

export function initScenarioPicker() {
  const container = document.getElementById('scenario-picker');
  const mobileMq = window.matchMedia('(max-width: 1024px)');

  const hotspot = document.createElement('div');
  hotspot.className = 'scenario-hotspot';
  container.appendChild(hotspot);

  const trigger = document.createElement('div');
  trigger.className = 'scenario-trigger';
  trigger.textContent = 'Select Scenario \u25BC';
  container.appendChild(trigger);

  const dropdown = document.createElement('div');
  dropdown.className = 'scenario-dropdown';
  container.appendChild(dropdown);

  function isMobileViewport() {
    return mobileMq.matches;
  }

  function setPeek(peeking) {
    if (!isMobileViewport() || container.classList.contains('open')) return;
    container.classList.toggle('peek', peeking);
  }

  function closePanel() {
    container.classList.remove('open', 'peek');
  }

  function openPanel() {
    container.classList.add('open');
    container.classList.remove('peek');
  }

  trigger.onclick = (e) => {
    e.stopPropagation();
    if (container.classList.contains('open')) closePanel();
    else openPanel();
  };

  hotspot.addEventListener('pointerenter', () => setPeek(true));
  hotspot.addEventListener('touchstart', (e) => {
    e.stopPropagation();
    openPanel();
  }, { passive: true });

  container.addEventListener('pointerleave', () => setPeek(false));
  dropdown.addEventListener('click', (e) => e.stopPropagation());

  document.addEventListener('click', (e) => {
    if (!container.contains(e.target)) {
      closePanel();
    }
  });
  window.addEventListener('scroll', closePanel, { passive: true });
  mobileMq.addEventListener('change', closePanel);

  function render() {
    const manifest = state.get('manifest');
    const platformId = state.get('currentPlatform');
    if (!manifest || !platformId) return;

    const platform = manifest.platforms.find(p => p.id === platformId);
    if (!platform) { dropdown.innerHTML = ''; return; }

    dropdown.innerHTML = '';
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
      card.onclick = () => {
        state.set('mode', 'static');
        state.set('currentScenario', sc.id);
        closePanel();
      };
      dropdown.appendChild(card);
    });

    // Auto-select first scenario
    if (platform.scenarios.length && state.get('mode') !== 'live') {
      const current = state.get('currentScenario');
      if (!current || !platform.scenarios.find(s => s.id === current)) {
        state.set('currentScenario', platform.scenarios[0].id);
      }
    }
  }

  state.on('manifest', render);
  state.on('currentPlatform', () => {
    closePanel();
    render();
  });

  state.on('currentScenario', (id) => {
    dropdown.querySelectorAll('.scenario-card').forEach(card => {
      card.classList.toggle('active', card.dataset.id === id);
    });

    // Update trigger text to show selected scenario name
    const manifest = state.get('manifest');
    const platformId = state.get('currentPlatform');
    if (manifest && platformId) {
      const platform = manifest.platforms.find(p => p.id === platformId);
      const sc = platform?.scenarios.find(s => s.id === id);
      if (sc) {
        trigger.textContent = `${sc.title} \u25BC`;
      }
    }
  });
}
