import { after, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const vite = await createServer({
  configFile: resolve(frontendRoot, 'vite.config.js'),
  root: frontendRoot,
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'error',
});

const [{ OverviewKPIs }, { EmissionAnalytics }, { SimulationControls }] = await Promise.all([
  vite.ssrLoadModule('/src/components/OverviewKPIs.jsx'),
  vite.ssrLoadModule('/src/components/EmissionAnalytics.jsx'),
  vite.ssrLoadModule('/src/components/SimulationControls.jsx'),
]);

after(async () => vite.close());

function render(Component, props) {
  return renderToStaticMarkup(React.createElement(Component, props));
}

describe('dashboard metric components', () => {
  it('formats metrics with units and distinguishes snapshot wait from cumulative delay', () => {
    const html = render(OverviewKPIs, {
      metrics: {
        total_vehicles: 27,
        throughput_vehicles: 101,
        mean_speed_kmh: 43.087,
        mean_instantaneous_waiting_time_s: 353.63,
        cumulative_delay_veh_s: 7657,
        total_co2_kg: 45.2659,
        total_nox_g: 36.9753,
        total_fuel_liters: 19.5378,
      },
      simStatus: { running: true, paused: false },
    });

    for (const text of [
      '3 / 3', 'Active Vehicles', '27', 'Completed corridor trips', '43.09 km/h',
      'Mean Snapshot Wait', '353.63 s', 'Cumulative Delay', '7657.00 veh·s',
      '45.2659 kg', '36.9753 g', '19.5378 L',
      'Vehicles currently in network', 'Gasoline equivalent',
    ]) assert.ok(html.includes(text), `expected dashboard markup to include ${text}`);
    assert.ok(html.includes('Estimated gasoline equivalent using ρ = 0.75 kg/L'));
    assert.ok(!html.includes('truncate'));
    assert.ok(!html.includes('Last completed simulation snapshot'));
  });

  it('renders unavailable KPI and emissions values as unavailable, not zero', () => {
    const kpis = render(OverviewKPIs, { metrics: null, simStatus: { running: false } });
    const stoppedSnapshot = render(OverviewKPIs, {
      metrics: { total_vehicles: 0 },
      simStatus: { status: 'STOPPED', running: false, paused: false },
    });
    const analytics = render(EmissionAnalytics, { metrics: null, history: [] });

    assert.ok(kpis.includes('—'));
    assert.ok(stoppedSnapshot.includes('Last completed simulation snapshot'));
    assert.ok(analytics.includes('—'));
    assert.ok(!analytics.includes('0.0000'));
    assert.ok(analytics.includes('Awaiting simulation telemetry data points'));
  });

  it('renders the chart state for accumulated history and the single-snapshot state', () => {
    const onePoint = render(EmissionAnalytics, {
      metrics: { total_co2_kg: 1, total_fuel_liters: 0.4 },
      history: [{ time: '1.0', co2_kg: 1, fuel_liters: 0.4, nox_g: null }],
    });
    const multiplePoints = render(EmissionAnalytics, {
      metrics: { total_co2_kg: 2, total_fuel_liters: 0.8 },
      history: [
        { time: '1.0', co2_kg: 1, fuel_liters: 0.4, nox_g: null },
        { time: '2.0', co2_kg: 2, fuel_liters: 0.8, nox_g: null },
      ],
    });

    assert.ok(onePoint.includes('One current snapshot is available'));
    assert.ok(!multiplePoints.includes('One current snapshot is available'));
    assert.ok(!multiplePoints.includes('Awaiting simulation telemetry data points'));
  });

  it('exposes start controls after stopped and completed runs, and stop controls while running', () => {
    for (const status of ['STOPPED', 'COMPLETED']) {
      const html = render(SimulationControls, {
        simStatus: { status, running: false, paused: false, simulation_time: 600, duration: 600 },
      });
      assert.ok(html.includes('Start Simulation'));
      assert.ok(!html.includes('>Stop</span>'));
    }

    const running = render(SimulationControls, {
      simStatus: { status: 'RUNNING', running: true, paused: false, simulation_time: 12, duration: 600 },
    });
    assert.ok(running.includes('Pause'));
    assert.ok(running.includes('>Stop</span>'));
    assert.ok(!running.includes('Start Simulation'));
  });
});
