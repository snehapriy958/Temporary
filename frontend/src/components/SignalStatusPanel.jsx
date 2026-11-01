import React from 'react';
import { TrafficCone, Clock, AlertTriangle, ShieldCheck } from 'lucide-react';

export function SignalStatusPanel({ signals, junctions }) {
  const junctionList = [
    { id: 'J1', name: 'J1 Hosur Feeder (North)', tls: '1617743335' },
    { id: 'J2', name: 'J2 Silk Board Central', tls: 'GS_cluster_10282769895...' },
    { id: 'J3', name: 'J3 Hosur Feeder (South)', tls: '6970466614' },
  ];

  const getPhaseName = (junctionId, phase) => {
    if (junctionId === 'J2') {
      if (phase === 0) return 'Phase 0: Hosur Corridor Green';
      if (phase === 1) return 'Phase 1: Hosur Yellow Transition';
      if (phase === 2) return 'Phase 2: Madiwala Road Green';
      if (phase === 3) return 'Phase 3: Madiwala Yellow Transition';
    } else {
      if (phase === 2) return 'Phase 2: Hosur Corridor Green';
      if (phase === 3) return 'Phase 3: Hosur Yellow Transition';
      if (phase === 0) return 'Phase 0: Side Cross Green';
      if (phase === 1) return 'Phase 1: Side Yellow Transition';
    }
    return `Phase ${phase}`;
  };

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <TrafficCone className="h-5 w-5 text-amber-600" />
          <h2 className="text-sm font-bold tracking-wide text-slate-900 uppercase">
            Signal Controller Telemetry
          </h2>
        </div>
        <span className="text-xs text-slate-500">
          Min/Max Green Bounds & Yellow Clearance Enforced
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {junctionList.map((junc) => {
          const sig = signals?.[junc.id];
          const st = junctions?.[junc.id];

          const isGreen = sig?.is_green ?? false;
          const isYellow = sig?.is_yellow ?? false;
          const isRed = !isGreen && !isYellow;
          const isCongested = (st?.total_queue || 0) > 10;
          const isEmergencyLocked = sig?.emergency_locked || false;

          return (
            <div
              key={junc.id}
              className={`rounded-xl border p-4 transition relative ${
                isCongested
                  ? 'border-rose-400 bg-rose-50/30 shadow-md'
                  : isEmergencyLocked
                  ? 'border-rose-400 bg-rose-50/40'
                  : 'border-slate-200 bg-slate-50 hover:bg-white hover:border-slate-300 hover:shadow-sm'
              }`}
            >
              {/* Header */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="h-6 w-6 rounded bg-teal-100 text-teal-800 font-mono font-bold text-xs flex items-center justify-center border border-teal-200">
                    {junc.id}
                  </span>
                  <div>
                    <h3 className="text-xs font-bold text-slate-900">{junc.name}</h3>
                    <p className="text-[10px] text-slate-500 font-mono truncate">{junc.tls}</p>
                  </div>
                </div>

                {/* Emergency Lock Pill */}
                {isEmergencyLocked && (
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-50 text-rose-700 border border-rose-300 animate-pulse">
                    EMERGENCY LOCK
                  </span>
                )}
              </div>

              {/* Traffic Light Head Visualizer */}
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-2.5 flex items-center justify-around mb-3 shadow-inner">
                {/* Red Light */}
                <div className="flex flex-col items-center gap-1">
                  <div
                    className={`h-7 w-7 rounded-full border transition-all duration-300 ${
                      isRed
                        ? 'bg-rose-500 border-rose-400 shadow-lg shadow-rose-500/50'
                        : 'bg-rose-950/40 border-rose-900/30 opacity-30'
                    }`}
                  />
                  <span className="text-[9px] uppercase tracking-wider text-slate-400">Red</span>
                </div>

                {/* Yellow Light */}
                <div className="flex flex-col items-center gap-1">
                  <div
                    className={`h-7 w-7 rounded-full border transition-all duration-300 ${
                      isYellow
                        ? 'bg-amber-400 border-amber-300 shadow-lg shadow-amber-400/50'
                        : 'bg-amber-950/40 border-amber-900/30 opacity-30'
                    }`}
                  />
                  <span className="text-[9px] uppercase tracking-wider text-slate-400">Yellow</span>
                </div>

                {/* Green Light */}
                <div className="flex flex-col items-center gap-1">
                  <div
                    className={`h-7 w-7 rounded-full border transition-all duration-300 ${
                      isGreen
                        ? 'bg-emerald-500 border-emerald-400 shadow-lg shadow-emerald-500/50'
                        : 'bg-emerald-950/40 border-emerald-900/30 opacity-30'
                    }`}
                  />
                  <span className="text-[9px] uppercase tracking-wider text-slate-400">Green</span>
                </div>
              </div>

              {/* Phase description */}
              <div className="bg-slate-100 rounded px-2.5 py-1 text-xs text-slate-800 font-mono mb-3 border border-slate-200 text-center font-medium">
                {getPhaseName(junc.id, sig?.current_phase ?? 0)}
              </div>

              {/* Timing meters */}
              <div className="grid grid-cols-2 gap-2 text-xs mb-3">
                <div className="bg-white p-2 rounded border border-slate-200">
                  <span className="text-[10px] text-slate-500 block">Elapsed In Phase</span>
                  <span className="font-mono font-bold text-slate-900">
                    {sig?.phase_elapsed ? `${sig.phase_elapsed.toFixed(1)}s` : '0.0s'}
                  </span>
                </div>
                <div className="bg-white p-2 rounded border border-slate-200">
                  <span className="text-[10px] text-slate-500 block">Min / Max Green</span>
                  <span className="font-mono text-slate-700 font-semibold">
                    {sig?.min_green || 15}s / {sig?.max_green || 60}s
                  </span>
                </div>
              </div>

              {/* Approach Queues */}
              <div className="text-xs pt-2 border-t border-slate-200">
                <div className="flex justify-between items-center mb-1">
                  <span className="text-slate-500 text-[11px]">Total Junction Queue:</span>
                  <span className={`font-mono font-bold ${isCongested ? 'text-rose-600' : 'text-slate-900'}`}>
                    {st?.total_queue || 0} veh
                  </span>
                </div>
                {st?.approach_queues && Object.entries(st.approach_queues).map(([appr, q]) => (
                  <div key={appr} className="flex justify-between text-[11px] text-slate-600">
                    <span className="truncate max-w-[140px] capitalize">{appr.replace('_', ' ')}:</span>
                    <span className="font-mono font-semibold">{q} veh</span>
                  </div>
                ))}
              </div>

              {/* Congestion warning banner */}
              {isCongested && (
                <div className="mt-2.5 p-1.5 rounded bg-rose-50 border border-rose-200 text-rose-700 text-[10px] flex items-center gap-1 font-medium">
                  <AlertTriangle className="h-3 w-3 flex-shrink-0 text-rose-600" />
                  <span>Heavy queue detected (&gt; 10 veh)</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
