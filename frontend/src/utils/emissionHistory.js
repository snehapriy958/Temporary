export function emissionHistoryPoint(metrics) {
  const simulationTime = Number(metrics?.simulation_time);
  if (!Number.isFinite(simulationTime) || simulationTime <= 0) return null;
  if (metrics.total_co2_kg == null && metrics.total_fuel_liters == null) return null;

  return {
    time: simulationTime.toFixed(1),
    co2_kg: metrics.total_co2_kg ?? null,
    fuel_liters: metrics.total_fuel_liters ?? null,
    nox_g: metrics.total_nox_g ?? null,
  };
}

export function appendEmissionHistory(history, metrics, reset = false) {
  const base = reset ? [] : history;
  const point = emissionHistoryPoint(metrics);
  if (!point) return base;

  const latestTime = Number(base.at(-1)?.time);
  if (Number.isFinite(latestTime) && Number(point.time) <= latestTime) return base;

  return [...base, point].slice(-30);
}
