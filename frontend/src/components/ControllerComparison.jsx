import React from 'react';
import { GitCompare, CheckCircle2, XCircle, Info, AlertCircle } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid } from 'recharts';

const METRIC_DEFINITIONS = [
  { key: 'mean_travel_time_s', label: 'Corridor Travel Time (s)' },
  { key: 'total_waiting_time_s', label: 'Average Wait Time (s)' },
  { key: 'mean_queue', label: 'Mean Corridor Queue (veh)' },
  { key: 'mean_speed_kmh', label: 'Average Speed (km/h)' },
  { key: 'total_co2_kg', label: 'Total CO₂ (kg)' },
  { key: 'total_fuel_liters', label: 'Estimated Fuel Volume (L)' },
  { key: 'emergency_traversal_duration_s', label: 'Ambulance Clearance (s)' },
];

const CONTROLLER_COLORS = [
  '#64748b', // Slate for baseline
  '#0d9488', // Teal for coordinated
  '#059669', // Emerald
  '#d97706', // Amber
  '#7c3aed', // Violet/Purple
];

export function ControllerComparison({ compareData, isLoading = false, error = null }) {
  // 1. Error state: API unavailable or call failed
  if (error) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <div className="flex items-center gap-2 border-b border-slate-200 pb-3 mb-4">
          <GitCompare className="h-5 w-5 text-purple-600" />
          <h2 className="text-sm font-bold tracking-wide text-slate-900 uppercase">
            Signal Controller Empirical Benchmark Comparison
          </h2>
        </div>
        <div className="py-12 flex flex-col items-center justify-center text-center">
          <div className="p-3 bg-rose-50 border border-rose-200 rounded-full mb-3 text-rose-600">
            <AlertCircle className="h-6 w-6" />
          </div>
          <h3 className="text-sm font-semibold text-slate-900 mb-1">Benchmark Data Unavailable</h3>
          <p className="text-xs text-slate-500 max-w-md">
            {typeof error === 'string' ? error : 'Unable to retrieve controller benchmark comparison from backend API.'}
          </p>
        </div>
      </div>
    );
  }

  // 2. Loading state: Waiting for API response
  if (isLoading || (!compareData && !error)) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <div className="flex items-center gap-2 border-b border-slate-200 pb-3 mb-4">
          <GitCompare className="h-5 w-5 text-purple-600 animate-pulse" />
          <h2 className="text-sm font-bold tracking-wide text-slate-900 uppercase">
            Signal Controller Empirical Benchmark Comparison
          </h2>
        </div>
        <div className="py-12 flex flex-col items-center justify-center text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-2 border-teal-600 border-t-transparent mb-3" />
          <p className="text-xs font-mono text-slate-500">Loading empirical benchmark metrics...</p>
        </div>
      </div>
    );
  }

  const controllers = compareData?.controllers || [];

  // 3. Empty state: API succeeded but no controllers returned
  if (controllers.length === 0) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <div className="flex items-center gap-2 border-b border-slate-200 pb-3 mb-4">
          <GitCompare className="h-5 w-5 text-purple-600" />
          <h2 className="text-sm font-bold tracking-wide text-slate-900 uppercase">
            Signal Controller Empirical Benchmark Comparison
          </h2>
        </div>
        <div className="py-12 flex flex-col items-center justify-center text-center">
          <Info className="h-6 w-6 text-slate-400 mb-2" />
          <h3 className="text-sm font-semibold text-slate-900 mb-1">No Benchmark Records Found</h3>
          <p className="text-xs text-slate-500">
            No controller benchmark records are currently registered for this corridor network.
          </p>
        </div>
      </div>
    );
  }

  // Filter controllers that have empirical data or are implemented
  const activeControllers = controllers.filter(
    (ctrl) => ctrl.status === 'Implemented' || ctrl.mean_travel_time_s != null
  );

  // Derive dynamic chart metrics from the active controllers
  const chartData = METRIC_DEFINITIONS.map(({ key, label }) => {
    const row = { metric: label };
    let hasValue = false;
    activeControllers.forEach((ctrl) => {
      const val = ctrl[key];
      if (val !== null && val !== undefined && !Number.isNaN(Number(val))) {
        row[ctrl.controller_name] = Number(val);
        hasValue = true;
      } else {
        row[ctrl.controller_name] = null;
      }
    });
    return hasValue ? row : null;
  }).filter(Boolean);

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <GitCompare className="h-5 w-5 text-purple-600" />
          <h2 className="text-sm font-bold tracking-wide text-slate-900 uppercase">
            Signal Controller Empirical Benchmark Comparison
          </h2>
        </div>
        <span className="text-xs font-mono text-slate-500">
          {compareData?.network || 'Silk Board Corridor (J1 -> J2 -> J3)'}
          {compareData?.benchmark_duration_s ? ` • ${compareData.benchmark_duration_s}s window` : ''}
        </span>
      </div>

      {/* Comparison Chart */}
      <div className="h-64 w-full mb-6">
        <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-1">
          Performance Comparison (Lower is Better, except Speed)
        </h3>
        <p className="text-[10px] text-slate-500 mb-2">
          Note: Fuel volumes are estimated gasoline equivalents (ρ = 0.75 kg/L).
        </p>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 25 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="metric" stroke="#64748b" tick={{ fontSize: 10, fill: '#64748b' }} angle={-15} textAnchor="end" />
              <YAxis stroke="#64748b" tick={{ fontSize: 10, fill: '#64748b' }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#ffffff',
                  borderColor: '#e2e8f0',
                  color: '#0f172a',
                  borderRadius: '0.5rem',
                  fontSize: '11px',
                  boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
                }}
              />
              <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
              {activeControllers.map((ctrl, idx) => (
                <Bar
                  key={ctrl.controller_name}
                  dataKey={ctrl.controller_name}
                  fill={CONTROLLER_COLORS[idx % CONTROLLER_COLORS.length]}
                  name={ctrl.controller_name}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-slate-400 text-xs font-mono border border-dashed border-slate-200 rounded-lg">
            <Info className="h-5 w-5 mb-2 text-slate-400" />
            <span>No numeric performance metrics available to chart for current controllers.</span>
          </div>
        )}
      </div>

      {/* Benchmarks Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border border-slate-200 rounded-lg overflow-hidden">
          <thead className="bg-slate-100 text-slate-700 text-[11px] uppercase font-mono border-b border-slate-200">
            <tr>
              <th className="py-2.5 px-3">Controller Architecture</th>
              <th className="py-2.5 px-3">Status</th>
              <th className="py-2.5 px-3">Travel Time</th>
              <th className="py-2.5 px-3">Mean Speed</th>
              <th className="py-2.5 px-3">Wait Time</th>
              <th className="py-2.5 px-3">Corridor Queue</th>
              <th className="py-2.5 px-3">CO₂ / Estimated Fuel Volume (L)</th>
              <th className="py-2.5 px-3">Ambulance Traversal</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 font-mono">
            {controllers.map((ctrl, i) => {
              const isImplemented = ctrl.status === 'Implemented';
              return (
                <tr
                  key={i}
                  className={`hover:bg-slate-50 transition ${
                    isImplemented ? 'bg-white' : 'bg-slate-50/50 opacity-75'
                  }`}
                >
                  <td className="py-3 px-3 font-semibold text-slate-900">
                    <div>{ctrl.controller_name}</div>
                    <div className="text-[10px] text-slate-500 font-sans mt-0.5 max-w-xs line-clamp-1">
                      {ctrl.description}
                    </div>
                  </td>
                  <td className="py-3 px-3">
                    {isImplemented ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-300">
                        <CheckCircle2 className="h-3 w-3" />
                        <span>Implemented</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-rose-50 text-rose-700 border border-rose-300">
                        <XCircle className="h-3 w-3" />
                        <span>Not implemented</span>
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-3 text-slate-700">
                    {ctrl.mean_travel_time_s != null ? `${ctrl.mean_travel_time_s}s` : '—'}
                  </td>
                  <td className="py-3 px-3 text-teal-700 font-bold">
                    {ctrl.mean_speed_kmh != null ? `${ctrl.mean_speed_kmh} km/h` : '—'}
                  </td>
                  <td className="py-3 px-3 text-slate-700">
                    {ctrl.total_waiting_time_s != null ? `${ctrl.total_waiting_time_s}s` : '—'}
                  </td>
                  <td className="py-3 px-3 text-slate-700">
                    {ctrl.mean_queue != null ? `${ctrl.mean_queue} veh` : '—'}
                  </td>
                  <td className="py-3 px-3 text-slate-700">
                    {ctrl.total_co2_kg != null ? (
                      <div>
                        <div>{ctrl.total_co2_kg} kg CO₂</div>
                        {ctrl.total_fuel_liters != null && (
                          <div className="text-[10px] text-amber-700 font-semibold" title="Gasoline equivalent (ρ = 0.75 kg/L)">
                            {ctrl.total_fuel_liters} L (est. gasoline-eq)
                          </div>
                        )}
                      </div>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="py-3 px-3 text-emerald-700 font-bold">
                    {ctrl.emergency_traversal_duration_s != null ? `${ctrl.emergency_traversal_duration_s}s` : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Explanatory notes on PPO & DQN */}
      <div className="mt-4 p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-700">
        <div className="flex items-start gap-2">
          <Info className="h-4 w-4 text-teal-600 flex-shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-semibold text-slate-900">AI Policy Roadmap (PPO / DQN Status):</p>
            <p className="text-[11px] text-slate-600">
              The simulation engine exposes clean, normalized observation hooks via <code className="text-teal-800 bg-slate-100 px-1 py-0.5 rounded font-mono border border-slate-200">sim.get_ai_observations()</code> for J1, J2, and J3 (queues, elapsed green, inflow, speeds, emergency flags). However, neural network policy weights, Gym training environments, and reward convergence checkpoints are not yet trained. In accordance with task guidelines, no artificial results or manufactured training curves are reported.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
