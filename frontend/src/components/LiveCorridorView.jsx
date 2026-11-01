import React from 'react';
import { ShieldAlert, ArrowDown, WifiOff } from 'lucide-react';

export function LiveCorridorView({ junctions, signals, emergencies, isStale }) {
  const j1 = junctions?.J1;
  const j2 = junctions?.J2;
  const j3 = junctions?.J3;

  const s1 = signals?.J1;
  const s2 = signals?.J2;
  const s3 = signals?.J3;

  const getSignalBadge = (sig) => {
    if (!sig) return { bg: 'bg-slate-100 text-slate-500 border-slate-200', dot: 'bg-slate-400', label: 'OFF' };
    if (sig.is_green) return { bg: 'bg-emerald-50 text-emerald-700 border-emerald-300', dot: 'bg-emerald-500', label: `GREEN (P${sig.current_phase})` };
    if (sig.is_yellow) return { bg: 'bg-amber-50 text-amber-800 border-amber-300', dot: 'bg-amber-500', label: `YELLOW (P${sig.current_phase})` };
    return { bg: 'bg-rose-50 text-rose-700 border-rose-300', dot: 'bg-rose-500', label: `RED (P${sig.current_phase})` };
  };

  const getDensityColor = (queue) => {
    if (!queue || queue <= 2) return 'text-emerald-700 bg-emerald-50 border-emerald-200';
    if (queue <= 7) return 'text-amber-800 bg-amber-50 border-amber-200';
    return 'text-rose-700 bg-rose-50 border-rose-200 font-bold';
  };

  const hasEmergency = emergencies?.active_emergency;
  const lockedJunctions = emergencies?.emergency_locked_junctions || [];

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm relative overflow-hidden">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6 border-b border-slate-200 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold tracking-wide text-slate-900 uppercase">
              Silk Board Corridor Live Topology
            </h2>
            <span className="text-[11px] font-mono text-slate-500">
              Hosur Road (J1 &rarr; J2 &rarr; J3)
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            Real SUMO edges: 172853382#2 &rarr; 172853382#3 &rarr; 1148717038#0 &rarr; 40696223#1
          </p>
        </div>

        {/* Stale Data Warning */}
        {isStale && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-amber-50 text-amber-800 border border-amber-300 text-xs">
            <WifiOff className="h-3.5 w-3.5" />
            <span>Connection offline / Stale data</span>
          </div>
        )}

        {hasEmergency && (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-rose-50 text-rose-700 border border-rose-300 text-xs font-semibold animate-pulse">
            <ShieldAlert className="h-4 w-4" />
            <span>Emergency Green Wave Active</span>
          </div>
        )}
      </div>

      {/* Corridor Diagram */}
      <div className="flex flex-col items-center justify-center py-4 relative">
        {/* =========================================
            JUNCTION 1 (J1 - Upstream Feeder Signal)
            ========================================= */}
        <div className="w-full max-w-xl bg-slate-50 border border-slate-200 rounded-xl p-4 relative shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="h-6 w-6 rounded bg-teal-100 text-teal-800 font-mono font-bold text-xs flex items-center justify-center border border-teal-200">
                J1
              </span>
              <div>
                <h3 className="text-xs font-bold text-slate-900 uppercase">
                  Hosur Rd North Feeder
                </h3>
                <span className="text-[10px] text-slate-500 font-mono">TLS: 1617743335</span>
              </div>
            </div>

            {/* Signal Badge */}
            <div className={`px-2.5 py-1 rounded border text-xs flex items-center gap-1.5 ${getSignalBadge(s1).bg}`}>
              <span className={`h-2 w-2 rounded-full ${getSignalBadge(s1).dot || 'bg-slate-400'}`} />
              <span className="font-semibold">{getSignalBadge(s1).label}</span>
            </div>
          </div>

          {/* Stats Bar */}
          <div className="grid grid-cols-4 gap-2 text-center text-xs pt-2 border-t border-slate-200">
            <div>
              <span className="text-[10px] text-slate-500 block">Vehicles</span>
              <span className="font-mono font-semibold text-slate-900">{j1?.vehicle_count || 0}</span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 block">Queue</span>
              <span className={`px-1.5 py-0.5 rounded text-[11px] border ${getDensityColor(j1?.total_queue)}`}>
                {j1?.total_queue || 0} veh
              </span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 block">Speed</span>
              <span className="font-mono text-slate-700">{j1?.average_speed_kmh || 0} km/h</span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 block">Wait</span>
              <span className="font-mono text-slate-700">{j1?.total_waiting_time || 0}s</span>
            </div>
          </div>

          {/* Side Approach Note */}
          <div className="mt-2 text-[10px] text-slate-500 flex justify-between">
            <span>Approaches: Hosur Arterial (2 lanes) + Side Cross (-148697299_0)</span>
            {lockedJunctions.includes('J1') && (
              <span className="text-rose-600 font-semibold">&bull; Emergency Preemption Locked</span>
            )}
          </div>
        </div>

        {/* Arterial Connecting Link J1 -> J2 */}
        <div className="flex flex-col items-center my-2 text-slate-400">
          <div className="h-6 w-0.5 bg-teal-400" />
          <div className="flex items-center gap-1 text-[11px] font-mono text-slate-600 bg-white px-2 py-0.5 rounded border border-slate-200 shadow-sm">
            <ArrowDown className="h-3 w-3 text-teal-600 animate-bounce" />
            <span>Edge: 172853382#3 (Corridor Inflow &rarr; J2)</span>
          </div>
          <div className="h-6 w-0.5 bg-teal-400" />
        </div>

        {/* =========================================
            JUNCTION 2 (J2 - Silk Board Primary Junction)
            ========================================= */}
        <div className="w-full max-w-xl bg-white border-2 border-teal-500 rounded-xl p-4 relative shadow-md">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="h-7 w-7 rounded-lg bg-teal-600 text-white font-mono font-bold text-sm flex items-center justify-center shadow-sm">
                J2
              </span>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold text-slate-900 uppercase">
                    Central Silk Board Junction
                  </h3>
                  <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-teal-50 text-teal-700 border border-teal-200">
                    HUB
                  </span>
                </div>
                <span className="text-[10px] text-slate-500 font-mono">
                  TLS: GS_cluster_10282769895...
                </span>
              </div>
            </div>

            {/* Signal Badge */}
            <div className={`px-3 py-1.5 rounded-lg border text-xs flex items-center gap-1.5 shadow-sm ${getSignalBadge(s2).bg}`}>
              <span className={`h-2.5 w-2.5 rounded-full ${getSignalBadge(s2).dot || 'bg-slate-400'}`} />
              <span className="font-bold">{getSignalBadge(s2).label}</span>
            </div>
          </div>

          {/* Stats Bar */}
          <div className="grid grid-cols-4 gap-2 text-center text-xs pt-2.5 border-t border-slate-200">
            <div>
              <span className="text-[10px] text-slate-500 block">Vehicles</span>
              <span className="font-mono font-bold text-slate-900">{j2?.vehicle_count || 0}</span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 block">Corridor Queue</span>
              <span className={`px-1.5 py-0.5 rounded text-[11px] border ${getDensityColor(j2?.approach_queues?.corridor_hosur || j2?.total_queue)}`}>
                {j2?.approach_queues?.corridor_hosur || 0} veh
              </span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 block">Madiwala Queue</span>
              <span className={`px-1.5 py-0.5 rounded text-[11px] border ${getDensityColor(j2?.approach_queues?.madiwala)}`}>
                {j2?.approach_queues?.madiwala || 0} veh
              </span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 block">Avg Speed</span>
              <span className="font-mono text-teal-700 font-bold">{j2?.average_speed_kmh || 0} km/h</span>
            </div>
          </div>

          {/* Inter-Intersection Upstream Inflow Feedback */}
          <div className="mt-3 bg-teal-50/60 p-2 rounded-lg border border-teal-200/60 text-[11px] flex items-center justify-between text-slate-700">
            <span>Adaptive Anticipation: Upstream Hosur arrivals from J1 incorporated</span>
            {lockedJunctions.includes('J2') ? (
              <span className="text-rose-600 font-bold animate-pulse">&bull; Preemption Locked</span>
            ) : (
              <span className="text-emerald-700 font-semibold">&bull; Dynamic Inflow Pressure Active</span>
            )}
          </div>
        </div>

        {/* Arterial Connecting Link J2 -> J3 */}
        <div className="flex flex-col items-center my-2 text-slate-400">
          <div className="h-6 w-0.5 bg-teal-400" />
          <div className="flex items-center gap-1 text-[11px] font-mono text-slate-600 bg-white px-2 py-0.5 rounded border border-slate-200 shadow-sm">
            <ArrowDown className="h-3 w-3 text-teal-600 animate-bounce" />
            <span>Edge: 1148717038#0 (Hosur Southbound &rarr; J3)</span>
          </div>
          <div className="h-6 w-0.5 bg-teal-400" />
        </div>

        {/* =========================================
            JUNCTION 3 (J3 - Downstream Feeder Signal)
            ========================================= */}
        <div className="w-full max-w-xl bg-slate-50 border border-slate-200 rounded-xl p-4 relative shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="h-6 w-6 rounded bg-teal-100 text-teal-800 font-mono font-bold text-xs flex items-center justify-center border border-teal-200">
                J3
              </span>
              <div>
                <h3 className="text-xs font-bold text-slate-900 uppercase">
                  Hosur Rd South Feeder
                </h3>
                <span className="text-[10px] text-slate-500 font-mono">TLS: 6970466614</span>
              </div>
            </div>

            {/* Signal Badge */}
            <div className={`px-2.5 py-1 rounded border text-xs flex items-center gap-1.5 ${getSignalBadge(s3).bg}`}>
              <span className={`h-2 w-2 rounded-full ${getSignalBadge(s3).dot || 'bg-slate-400'}`} />
              <span className="font-semibold">{getSignalBadge(s3).label}</span>
            </div>
          </div>

          {/* Stats Bar */}
          <div className="grid grid-cols-4 gap-2 text-center text-xs pt-2 border-t border-slate-200">
            <div>
              <span className="text-[10px] text-slate-500 block">Vehicles</span>
              <span className="font-mono font-semibold text-slate-900">{j3?.vehicle_count || 0}</span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 block">Queue</span>
              <span className={`px-1.5 py-0.5 rounded text-[11px] border ${getDensityColor(j3?.total_queue)}`}>
                {j3?.total_queue || 0} veh
              </span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 block">Speed</span>
              <span className="font-mono text-slate-700">{j3?.average_speed_kmh || 0} km/h</span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 block">Exit Edge</span>
              <span className="font-mono text-slate-600 text-[10px]">40696223#1</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
