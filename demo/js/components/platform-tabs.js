import { state } from '../state.js';

const ICONS = { android: '\u{1F4F1}', ios: '\u{1F34F}', macos: '\u{1F5A5}', windows: '\u{1FA9F}', linux: '\u{1F427}' };

export function initPlatformTabs() {
  const container = document.getElementById('platform-tabs');

  state.on('manifest', (manifest) => {
    if (!manifest) return;
    container.innerHTML = '';
    manifest.platforms.forEach(p => {
      const btn = document.createElement('button');
      btn.className = 'platform-tab';
      btn.dataset.id = p.id;
      btn.textContent = `${ICONS[p.id] || ''} ${p.label}`;
      btn.onclick = () => state.set('currentPlatform', p.id);
      container.appendChild(btn);
    });
    // Select first platform
    if (manifest.platforms.length && !state.get('currentPlatform')) {
      state.set('currentPlatform', manifest.platforms[0].id);
    }
  });

  state.on('currentPlatform', (id) => {
    container.querySelectorAll('.platform-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.id === id);
    });
  });
}
