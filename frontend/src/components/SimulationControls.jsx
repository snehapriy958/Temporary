import React, { useState } from 'react';
import { Play, Pause, Square, RotateCcw, ShieldAlert, Settings, AlertCircle, CheckCircle } from 'lucide-react';
import { api } from '../services/api';

export function SimulationControls({ simStatus, onStatusRefresh }) {
  const [mode, setMode] = useState('coordinated');
  const [duration, setDuration] = useState(600);
  const [seed, setSeed] = useState(42);
  const [enableEmergency, setEnableEmergency] = useState(true);
  const [gui, setGui] = useState(false);

  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState({ type: null, message: '' });

  const isRunning = simStatus?.running && !simStatus?.paused;
  const isPaused = simStatus?.paused;
  const isStopped = !simStatus?.running;

  const showNotice = (type, message) => {
    setFeedback({ type, message });
    setTimeout(() => setFeedback({ type: null, message: '' }), 4000);
  };

  const handleStart = async () => {
    setLoading(true);
    try {
      const checkpointPath = mode === 'marl_ppo'
        ? 'checkpoints/p6/ppo_stage_a_best.json'
        : mode === 'marl_dqn'
          ? 'checkpoints/p6/dqn_stage_a_best.json'
          : undefined;
      const res = await api.startSimulation({
        mode,
        duration: Number(duration),
        seed: Number(seed),
        step_length: 1.0,
        decision_interval: 5.0,
        enable_emergency: enableEmergency,
        gui,
        checkpoint_path: checkpointPath,
      });
      showNotice('success', res.message || 'Simulation started.');
      if (onStatusRefresh) onStatusRefresh();
    } catch (err) {
      showNotice('error', err.message || 'Failed to start simulation.');
    } finally {
      setLoading(false);
    }
  };

  const handlePause = async () => {
    setLoading(true);
    try {
      const res = await api.pauseSimulation();
      showNotice('success', res.message || 'Simulation paused.');
      if (onStatusRefresh) onStatusRefresh();
    } catch (err) {
      showNotice('error', err.message || 'Failed to pause.');
    } finally {
      setLoading(false);
    }
  };

  const handleResume = async () => {
    setLoading(true);
    try {
      const res = await api.resumeSimulation();
      showNotice('success', res.message || 'Simulation resumed.');
      if (onStatusRefresh) onStatusRefresh();
    } catch (err) {
      showNotice('error', err.message || 'Failed to resume.');
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      const res = await api.stopSimulation();
      showNotice('success', res.message || 'Simulation stopped.');
      if (onStatusRefresh) onStatusRefresh();
    } catch (err) {
      showNotice('error', err.message || 'Failed to stop.');
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    setLoading(true);
    try {
      const res = await api.resetSimulation();
      showNotice('success', res.message || 'Simulation reset.');
      if (onStatusRefresh) onStatusRefresh();
    } catch (err) {
      showNotice('error', err.message || 'Failed to reset.');
    } finally {
      setLoading(false);
    }
  };

  const progressPercent = Math.min(
    100,
    Math.round(((simStatus?.simulation_time || 0) / (simStatus?.duration || 600)) * 100)
  );

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <Settings className="h-5 w-5 text-teal-600" />
          <h2 className="text-sm font-bold tracking-wide text-slate-900 uppercase">
            Simulation Control Deck
          </h2>
        </div>

        {/* Progress Display */}
        <div className="flex items-center gap-3 text-xs">
          <span className="text-slate-500">Simulation Time:</span>
          <span className="font-mono font-bold text-slate-900 bg-slate-100 px-2.5 py-1 rounded border border-slate-200">
            {simStatus?.simulation_time?.toFixed(1) || '0.0'}s / {simStatus?.duration ?? duration}s
          </span>
          <span className="text-slate-500 font-mono">({progressPercent}%)</span>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="w-full bg-slate-100 border border-slate-200 h-2 rounded-full mb-4 overflow-hidden">
        <div
          className={`h-full transition-all duration-300 ${
            isRunning ? 'bg-teal-600' : isPaused ? 'bg-amber-500' : 'bg-slate-300'
          }`}
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      {/* Form Controls */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 mb-4">
        {/* Mode Selector */}
        <div>
          <label className="block text-[11px] font-semibold text-slate-600 mb-1">
            Controller Mode
          </label>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            disabled={!isStopped || loading}
            className="w-full bg-slate-50 border border-slate-300 text-slate-900 rounded-lg px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-teal-500 outline-none disabled:opacity-50"
          >
            <option value="coordinated">Coordinated Adaptive (Silk Board)</option>
            <option value="baseline">Fixed-Time Baseline</option>
            <option value="marl_ppo">MARL PPO (Actor-Critic)</option>
            <option value="marl_dqn">MARL DQN (Double-DQN)</option>
          </select>
        </div>

        {/* Duration */}
        <div>
          <label className="block text-[11px] font-semibold text-slate-600 mb-1">
            Duration
          </label>
          <select
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            disabled={!isStopped || loading}
            className="w-full bg-slate-50 border border-slate-300 text-slate-900 rounded-lg px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-teal-500 outline-none disabled:opacity-50"
          >
            <option value={300}>300 seconds (5 min)</option>
            <option value={600}>600 seconds (10 min)</option>
            <option value={1200}>1200 seconds (20 min)</option>
          </select>
        </div>

        {/* Random Seed */}
        <div>
          <label className="block text-[11px] font-semibold text-slate-600 mb-1">
            Random Seed
          </label>
          <input
            type="number"
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value))}
            disabled={!isStopped || loading}
            className="w-full bg-slate-50 border border-slate-300 text-slate-900 rounded-lg px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-teal-500 outline-none disabled:opacity-50 font-mono"
          />
        </div>

        {/* Emergency Preemption Toggle */}
        <div className="flex flex-col justify-end">
          <label className="flex items-center gap-2 cursor-pointer bg-slate-50 border border-slate-300 px-3 py-1.5 rounded-lg text-xs text-slate-700 hover:bg-slate-100 transition">
            <input
              type="checkbox"
              checked={enableEmergency}
              onChange={(e) => setEnableEmergency(e.target.checked)}
              disabled={!isStopped || loading}
              className="accent-teal-600 rounded"
            />
            <ShieldAlert className="h-4 w-4 text-rose-600" />
            <span>Green Wave</span>
          </label>
        </div>

        {/* Headless vs GUI Toggle */}
        <div className="flex flex-col justify-end">
          <label className="flex items-center gap-2 cursor-pointer bg-slate-50 border border-slate-300 px-3 py-1.5 rounded-lg text-xs text-slate-700 hover:bg-slate-100 transition">
            <input
              type="checkbox"
              checked={gui}
              onChange={(e) => setGui(e.target.checked)}
              disabled={!isStopped || loading}
              className="accent-teal-600 rounded"
            />
            <span>sumo-gui</span>
          </label>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex flex-wrap items-center gap-2">
        {isStopped && (
          <button
            onClick={handleStart}
            disabled={loading}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-sm shadow-emerald-600/20 transition disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            <span>Start Simulation</span>
          </button>
        )}

        {isRunning && (
          <button
            onClick={handlePause}
            disabled={loading}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold shadow-sm shadow-amber-600/20 transition disabled:opacity-50"
          >
            <Pause className="h-4 w-4" />
            <span>Pause</span>
          </button>
        )}

        {isPaused && (
          <button
            onClick={handleResume}
            disabled={loading}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-semibold shadow-sm shadow-teal-600/20 transition disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            <span>Resume</span>
          </button>
        )}

        {!isStopped && (
          <button
            onClick={handleStop}
            disabled={loading}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold shadow-sm shadow-rose-600/20 transition disabled:opacity-50"
          >
            <Square className="h-4 w-4" />
            <span>Stop</span>
          </button>
        )}

        <button
          onClick={handleReset}
          disabled={loading}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300 text-xs font-semibold transition disabled:opacity-50 ml-auto"
        >
          <RotateCcw className="h-4 w-4 text-slate-500" />
          <span>Reset</span>
        </button>
      </div>

      {/* Feedback banner */}
      {feedback.type && (
        <div
          className={`mt-3 p-2.5 rounded-lg border text-xs flex items-center gap-2 ${
            feedback.type === 'success'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
              : 'bg-rose-50 border-rose-200 text-rose-800'
          }`}
        >
          {feedback.type === 'success' ? (
            <CheckCircle className="h-4 w-4 flex-shrink-0 text-emerald-600" />
          ) : (
            <AlertCircle className="h-4 w-4 flex-shrink-0 text-rose-600" />
          )}
          <span>{feedback.message}</span>
        </div>
      )}
    </div>
  );
}
