import React from 'react';
import { ShieldAlert, Siren, CheckCircle2, Clock, AlertCircle } from 'lucide-react';

export function EmergencyPanel({ emergencies }) {
  const isActive = emergencies?.active_emergency || false;
  const lockedJunctions = emergencies?.emergency_locked_junctions || [];
  const events = emergencies?.events || [];
  const activeVehicleId = emergencies?.active_vehicle_id;

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <Siren className={`h-5 w-5 ${isActive ? 'text-rose-600 animate-bounce' : 'text-slate-400'}`} />
          <h2 className="text-sm font-bold tracking-wide text-slate-900 uppercase">
            Emergency Green Wave Preemption
          </h2>
        </div>
        <span
          className={`px-2.5 py-1 rounded-full text-xs font-bold border ${
            isActive
              ? 'bg-rose-50 text-rose-700 border-rose-300 animate-pulse'
              : 'bg-slate-100 text-slate-600 border border-slate-200'
          }`}
        >
          {isActive ? 'PREEMPTION ACTIVE' : 'MONITORING STANDBY'}
        </span>
      </div>

      {/* Active Preemption Banner */}
      {isActive ? (
        <div className="bg-rose-50 border border-rose-300 rounded-xl p-4 mb-4">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg bg-rose-100 text-rose-700 border border-rose-200">
              <ShieldAlert className="h-6 w-6" />
            </div>
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-rose-900 uppercase">
                  Priority Ambulance Detected: {activeVehicleId || 'AMBULANCE_01'}
                </h3>
                <span className="text-xs font-mono text-rose-700 font-semibold">Green Wave Engaged</span>
              </div>
              <p className="text-xs text-rose-800/90 mt-1">
                Progressive priority lock initiated on Hosur Road Corridor. Conflicting side-street signals safely transitioned to red.
              </p>
              <div className="mt-3 flex items-center gap-2 text-xs">
                <span className="text-slate-600 font-medium">Locked Intersections:</span>
                {lockedJunctions.length > 0 ? (
                  lockedJunctions.map((j) => (
                    <span
                      key={j}
                      className="px-2 py-0.5 rounded bg-rose-100 text-rose-800 border border-rose-300 font-mono font-bold"
                    >
                      {j}
                    </span>
                  ))
                ) : (
                  <span className="text-slate-500">Approaching J1 stopline...</span>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 mb-4 text-center text-slate-600 text-xs">
          <span>No emergency vehicles actively detected along the Hosur Road corridor. Traversal detectors active at 250m approach threshold.</span>
        </div>
      )}

      {/* Traversal Events Log */}
      <div>
        <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">
          Emergency Traversal History ({events.length} Recorded)
        </h3>

        {events.length === 0 ? (
          <p className="text-xs text-slate-500 italic py-2">
            No emergency runs have occurred in this session.
          </p>
        ) : (
          <div className="overflow-x-auto border border-slate-200 rounded-lg">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-100 text-slate-700 font-mono text-[11px] uppercase border-b border-slate-200">
                <tr>
                  <th className="py-2 px-3">Vehicle ID</th>
                  <th className="py-2 px-3">Corridor</th>
                  <th className="py-2 px-3">Sim Time</th>
                  <th className="py-2 px-3">Traversal Time</th>
                  <th className="py-2 px-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 font-mono">
                {events.map((ev, idx) => (
                  <tr key={idx} className="hover:bg-slate-50 transition">
                    <td className="py-2.5 px-3 font-semibold text-slate-900">
                      {ev.vehicle_id}
                    </td>
                    <td className="py-2.5 px-3 text-slate-700">
                      {ev.affected_corridor}
                    </td>
                    <td className="py-2.5 px-3 text-slate-600">
                      {ev.simulation_time.toFixed(1)}s
                    </td>
                    <td className="py-2.5 px-3 text-emerald-700 font-bold">
                      {ev.traversal_duration > 0
                        ? `${ev.traversal_duration.toFixed(1)}s`
                        : 'Traversing...'}
                    </td>
                    <td className="py-2.5 px-3">
                      {ev.completed ? (
                        <span className="inline-flex items-center gap-1 text-emerald-700 text-[11px]">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          <span>Cleared</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-amber-700 text-[11px] animate-pulse">
                          <Clock className="h-3.5 w-3.5" />
                          <span>In Transit</span>
                        </span>
                      )}
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
