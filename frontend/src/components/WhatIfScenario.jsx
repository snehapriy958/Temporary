import React, { useState, useEffect } from 'react';
import { Layers, History, Play, CheckCircle2, RotateCcw } from 'lucide-react';
import { api } from '../services/api';

export function WhatIfScenario({ onRunScenario }) {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);

  // Scenario config
  const [scenarioMode, setScenarioMode] = useState('coordinated');
  const [scenarioDuration, setScenarioDuration] = useState(300);
  const [scenarioSeed, setScenarioSeed] = useState(101);
  const [scenarioEmergency, setScenarioEmergency] = useState(true);

  const fetchHistory = async () => {
    try {
      const data = await api.getExperimentsHistory();
      setHistory(data);
    } catch (e) {
      console.warn('Failed fetching history:', e);
    }
  };

  useEffect(() => {
    fetchHistory();
    const interval = setInterval(fetchHistory, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleLaunch = () => {
    if (onRunScenario) {
      const checkpointPath = scenarioMode === 'marl_ppo'
        ? 'checkpoints/p6/ppo_stage_a_best.json'
        : scenarioMode === 'marl_dqn'
          ? 'checkpoints/p6/dqn_stage_a_best.json'
          : undefined;
      onRunScenario({
        mode: scenarioMode,
        duration: Number(scenarioDuration),
        seed: Number(scenarioSeed),
        enable_emergency: scenarioEmergency,
        checkpoint_path: checkpointPath,
      });
    }
  };

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <Layers className="h-5 w-5 text-teal-600" />
          <h2 className="text-sm font-bold tracking-wide text-slate-900 uppercase">
            What-If Scenario Sandbox & Run History
          </h2>
        </div>
        <button
          onClick={fetchHistory}
          className="p-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-600 hover:text-slate-900 transition border border-slate-200"
          title="Refresh History"
        >
          <RotateCcw className="h-4 w-4" />
        </button>
      </div>

      {/* Scenario Config Bar */}
      <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 mb-5">
        <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3">
          Configure Custom Corridor Scenario
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 mb-3 text-xs">
          <div>
            <label className="block text-slate-600 mb-1 font-semibold">Controller</label>
            <select
              value={scenarioMode}
              onChange={(e) => setScenarioMode(e.target.value)}
              className="w-full bg-white border border-slate-300 text-slate-900 rounded px-2.5 py-1.5 outline-none focus:ring-1 focus:ring-teal-500"
            >
              <option value="coordinated">Coordinated Adaptive</option>
              <option value="baseline">Fixed-Time Baseline</option>
              <option value="marl_ppo">MARL PPO (Actor-Critic)</option>
              <option value="marl_dqn">MARL DQN (Double-DQN)</option>
            </select>
          </div>
          <div>
            <label className="block text-slate-600 mb-1 font-semibold">Duration (s)</label>
            <input
              type="number"
              value={scenarioDuration}
              onChange={(e) => setScenarioDuration(Number(e.target.value))}
              className="w-full bg-white border border-slate-300 text-slate-900 rounded px-2.5 py-1.5 outline-none focus:ring-1 focus:ring-teal-500 font-mono"
            />
          </div>
          <div>
            <label className="block text-slate-600 mb-1 font-semibold">Demand Seed</label>
            <input
              type="number"
              value={scenarioSeed}
              onChange={(e) => setScenarioSeed(Number(e.target.value))}
              className="w-full bg-white border border-slate-300 text-slate-900 rounded px-2.5 py-1.5 outline-none focus:ring-1 focus:ring-teal-500 font-mono"
            />
          </div>
          <div className="flex flex-col justify-end">
            <label className="flex items-center gap-2 cursor-pointer bg-white border border-slate-300 px-3 py-1.5 rounded text-slate-700 hover:bg-slate-50">
              <input
                type="checkbox"
                checked={scenarioEmergency}
                onChange={(e) => setScenarioEmergency(e.target.checked)}
                className="accent-teal-600"
              />
              <span>Ambulance Surge</span>
            </label>
          </div>
        </div>

        <button
          onClick={handleLaunch}
          className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-semibold shadow-sm transition"
        >
          <Play className="h-3.5 w-3.5" />
          <span>Launch Scenario in Simulator</span>
        </button>
      </div>

      {/* Historical Runs Stored in SQLite */}
      <div>
        <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2 flex items-center gap-1.5">
          <History className="h-4 w-4 text-slate-500" />
          <span>Stored SQLite Database Runs ({history.length})</span>
        </h3>

        {history.length === 0 ? (
          <p className="text-xs text-slate-500 italic py-3 text-center border border-dashed border-slate-200 rounded-lg">
            No historical experiment runs stored in database yet.
          </p>
        ) : (
          <div className="overflow-x-auto max-h-60 overflow-y-auto border border-slate-200 rounded-lg">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-slate-100 text-slate-700 text-[10px] uppercase border-b border-slate-200 sticky top-0">
                <tr>
                  <th className="py-2 px-3">Run UUID</th>
                  <th className="py-2 px-3">Mode</th>
                  <th className="py-2 px-3">Status</th>
                  <th className="py-2 px-3">Seed</th>
                  <th className="py-2 px-3">Simulated (s)</th>
                  <th className="py-2 px-3">Throughput</th>
                  <th className="py-2 px-3">CO₂ (kg)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-[11px]">
                {history.map((run) => (
                  <tr key={run.id} className="hover:bg-slate-50">
                    <td className="py-2 px-3 text-slate-600">{run.run_uuid}</td>
                    <td className="py-2 px-3 font-semibold uppercase text-teal-700">{run.mode}</td>
                    <td className="py-2 px-3">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                        run.status === 'COMPLETED'
                          ? 'bg-emerald-50 text-emerald-700 border border-emerald-300'
                          : run.status === 'RUNNING'
                          ? 'bg-teal-50 text-teal-700 border border-teal-300'
                          : 'bg-slate-100 text-slate-600 border border-slate-200'
                      }`}>
                        {run.status}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-slate-600">{run.seed}</td>
                    <td className="py-2 px-3 text-slate-900 font-semibold">{run.duration_simulated.toFixed(1)}s</td>
                    <td className="py-2 px-3 text-slate-700">
                      {run.summary_metrics?.throughput_vehicles ?? '—'}
                    </td>
                    <td className="py-2 px-3 text-teal-700 font-semibold">
                      {run.summary_metrics?.total_co2_kg ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
