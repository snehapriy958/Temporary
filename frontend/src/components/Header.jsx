import React, { useState, useEffect } from 'react';
import { Activity, Radio, Cpu, Clock, AlertTriangle } from 'lucide-react';

export function Header({ wsStatus, health, simStatus, onOpenOverride }) {
  const [currentTime, setCurrentTime] = useState(new Date().toLocaleTimeString());

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date().toLocaleTimeString());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const isWsConnected = wsStatus === 'CONNECTED';
  const isSimRunning = simStatus?.running && !simStatus?.paused;
  const isSimPaused = simStatus?.paused;

  return (
    <header className="border-b border-slate-200 bg-white/95 backdrop-blur px-6 py-4 flex flex-wrap items-center justify-between gap-4 sticky top-0 z-40 shadow-sm">
      {/* Title & Branding */}
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-lg bg-gradient-to-tr from-teal-600 to-emerald-600 flex items-center justify-center shadow-md shadow-teal-600/20">
          <Activity className="h-6 w-6 text-white" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold tracking-tight text-slate-900 uppercase">
              Bengaluru Traffic Coordination Center
            </h1>
            <span className="px-2 py-0.5 text-xs font-semibold rounded bg-teal-50 text-teal-700 border border-teal-200">
              Silk Board Corridor
            </span>
          </div>
          <p className="text-xs text-slate-500">
            Multi-Intersection Adaptive Signal & Emergency Preemption Hub (J1 &rarr; J2 &rarr; J3)
          </p>
        </div>
      </div>

      {/* Status Indicators & Clock */}
      <div className="flex items-center flex-wrap gap-4">
        {/* WebSocket Status */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-50 border border-slate-200 text-xs">
          <Radio className={`h-4 w-4 ${isWsConnected ? 'text-emerald-600 animate-pulse' : 'text-rose-600'}`} />
          <span className="text-slate-500">Stream:</span>
          <span className={`font-semibold ${isWsConnected ? 'text-emerald-600' : 'text-rose-600'}`}>
            {wsStatus}
          </span>
        </div>

        {/* SUMO Status */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-50 border border-slate-200 text-xs">
          <Cpu className="h-4 w-4 text-teal-600" />
          <span className="text-slate-500">SUMO:</span>
          <span className="font-semibold text-slate-800">
            {health?.sumo_available ? 'Online (v1.26)' : 'Offline'}
          </span>
        </div>

        {/* Simulation State Pill */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-50 border border-slate-200 text-xs">
          <span className="text-slate-500">Status:</span>
          <span
            className={`font-semibold px-2 py-0.5 rounded text-[11px] ${
              isSimRunning
                ? 'bg-emerald-50 text-emerald-700 border border-emerald-300'
                : isSimPaused
                ? 'bg-amber-50 text-amber-700 border border-amber-300'
                : 'bg-slate-100 text-slate-600 border border-slate-200'
            }`}
          >
            {isSimRunning ? 'RUNNING' : isSimPaused ? 'PAUSED' : 'STOPPED'}
          </span>
        </div>

        {/* Digital Clock */}
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-slate-50 border border-slate-200 text-xs text-slate-700">
          <Clock className="h-4 w-4 text-slate-400" />
          <span className="font-mono">{currentTime}</span>
        </div>

        {/* Manual Override Action */}
        <button
          onClick={onOpenOverride}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-300 text-xs font-semibold transition shadow-sm"
          title="Operator Manual Phase Override"
        >
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          <span>Manual Override</span>
        </button>
      </div>
    </header>
  );
}
