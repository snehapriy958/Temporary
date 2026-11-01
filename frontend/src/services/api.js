/**
 * frontend/src/services/api.js
 * 
 * Central API client for the Smart Traffic Coordination REST backend.
 */

const API_BASE = '/api';

async function fetchJson(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  try {
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    });

    if (!response.ok) {
      let errorDetail = `HTTP Error ${response.status}`;
      try {
        const errJson = await response.json();
        errorDetail = errJson.detail || errJson.message || errorDetail;
      } catch (_) {}
      throw new Error(errorDetail);
    }

    return await response.json();
  } catch (error) {
    console.error(`API Error on ${endpoint}:`, error.message);
    throw error;
  }
}

export const api = {
  // Health
  getHealth: () => fetchJson('/health'),

  // Simulation Controls
  getSimulationStatus: () => fetchJson('/simulation/status'),
  startSimulation: (params) =>
    fetchJson('/simulation/start', {
      method: 'POST',
      body: JSON.stringify(params),
    }),
  pauseSimulation: () => fetchJson('/simulation/pause', { method: 'POST' }),
  resumeSimulation: () => fetchJson('/simulation/resume', { method: 'POST' }),
  stopSimulation: () => fetchJson('/simulation/stop', { method: 'POST' }),
  resetSimulation: () => fetchJson('/simulation/reset', { method: 'POST' }),

  // Traffic & Metrics
  getTrafficLive: () => fetchJson('/traffic/live'),
  getTrafficMetrics: () => fetchJson('/traffic/metrics'),

  // Signals & Manual Override
  getSignals: () => fetchJson('/signals'),
  overrideSignal: (junctionId, targetPhase, confirmed) =>
    fetchJson('/signals/override', {
      method: 'POST',
      body: JSON.stringify({
        junction_id: junctionId,
        target_phase: targetPhase,
        confirmed: confirmed,
      }),
    }),

  // Emergencies
  getEmergencies: () => fetchJson('/emergencies'),

  // Risks & Hotspots
  getRisks: () => fetchJson('/risks'),

  // Decisions
  getDecisions: () => fetchJson('/decisions'),

  // Experiments & Benchmarks
  getExperimentsCompare: () => fetchJson('/experiments/compare'),
  getExperimentsHistory: () => fetchJson('/experiments/history'),
};
