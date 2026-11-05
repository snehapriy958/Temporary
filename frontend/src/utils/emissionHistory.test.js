import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { appendEmissionHistory, emissionHistoryPoint } from './emissionHistory.js';

describe('emissions history', () => {
  it('keeps available values and leaves missing measurements null', () => {
    assert.equal(emissionHistoryPoint({ simulation_time: 0, total_co2_kg: 1 }), null);
    assert.equal(emissionHistoryPoint({ simulation_time: 2 }), null);
    assert.deepEqual(
      emissionHistoryPoint({ simulation_time: 2.5, total_co2_kg: 1.2345, total_fuel_liters: null }),
      { time: '2.5', co2_kg: 1.2345, fuel_liters: null, nox_g: null },
    );
  });

  it('appends unique, ordered points and rejects duplicate or stale telemetry', () => {
    const first = appendEmissionHistory([], { simulation_time: 1, total_co2_kg: 1 });
    const second = appendEmissionHistory(first, { simulation_time: 2, total_co2_kg: 2 });
    assert.equal(second.length, 2);
    assert.deepEqual(
      appendEmissionHistory(second, { simulation_time: 2, total_co2_kg: 99 }),
      second,
    );
    assert.deepEqual(
      appendEmissionHistory(second, { simulation_time: 1, total_co2_kg: 99 }),
      second,
    );
    assert.deepEqual(second.map(({ time }) => Number(time)), [1, 2]);
  });

  it('resets history on session change and bounds retained chart points', () => {
    const history = Array.from({ length: 30 }, (_, index) => ({
      time: String(index + 1), co2_kg: index, fuel_liters: null, nox_g: null,
    }));
    const next = appendEmissionHistory(history, { simulation_time: 0.5, total_co2_kg: 3 }, true);
    assert.deepEqual(next, [{ time: '0.5', co2_kg: 3, fuel_liters: null, nox_g: null }]);

    const bounded = appendEmissionHistory(history, { simulation_time: 31, total_co2_kg: 31 });
    assert.equal(bounded.length, 30);
    assert.equal(bounded[0].time, '2');
    assert.equal(bounded.at(-1).time, '31.0');
  });
});
