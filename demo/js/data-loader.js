/**
 * Loads manifest and scenario data with caching.
 */

const cache = new Map();

export async function loadManifest() {
  if (cache.has('manifest')) return cache.get('manifest');
  const resp = await fetch('data/manifest.json');
  const data = await resp.json();
  cache.set('manifest', data);
  return data;
}

export async function loadScenario(platformId, scenarioId) {
  const key = `${platformId}/${scenarioId}`;
  if (cache.has(key)) return cache.get(key);

  const basePath = `data/${platformId}/${scenarioId}`;
  const [trajectory, agentLog] = await Promise.all([
    fetch(`${basePath}/trajectory.json`).then(r => r.json()),
    fetch(`${basePath}/agent-log.json`).then(r => r.json()),
  ]);

  // Resolve screenshot paths to full URLs relative to data dir
  for (const step of trajectory.steps) {
    if (step.screenshot) {
      step.screenshot = `${basePath}/${step.screenshot}`;
    }
  }

  const result = { trajectory, agentLog };
  cache.set(key, result);
  return result;
}
