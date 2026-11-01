import React from 'react';
import { AlertOctagon, Flame, Shield, MapPin, Info } from 'lucide-react';

export function RiskHotspotsPanel({ riskData }) {
  const zones = riskData?.risk_zones || [];
  const hotspots = riskData?.hotspots || [];

  const getRiskBadge = (level) => {
    switch (level?.toUpperCase()) {
      case 'CRITICAL':
        return 'bg-rose-50 text-rose-700 border-rose-300';
      case 'HIGH':
        return 'bg-amber-50 text-amber-800 border-amber-300';
      case 'MEDIUM':
        return 'bg-yellow-50 text-yellow-800 border-yellow-300';
      default:
        return 'bg-emerald-50 text-emerald-700 border-emerald-300';
    }
  };

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <AlertOctagon className="h-5 w-5 text-rose-600" />
          <h2 className="text-sm font-bold tracking-wide text-slate-900 uppercase">
            Accident Blackspots & MoRTH Risk Zones
          </h2>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-rose-600 font-bold">{riskData?.critical_zones || 0} Critical</span>
          <span className="text-slate-300">&bull;</span>
          <span className="text-amber-700 font-bold">{riskData?.high_zones || 0} High</span>
          <span className="text-slate-300">&bull;</span>
          <span className="text-slate-600">{riskData?.total_zones || 0} Zones</span>
        </div>
      </div>

      {/* Methodology Notice */}
      <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-700 mb-4 flex items-start gap-2">
        <Info className="h-4 w-4 text-teal-600 flex-shrink-0 mt-0.5" />
        <div>
          <p className="font-semibold text-slate-900">IRC / MoRTH Road Safety Audit Methodology</p>
          <p className="text-[11px] text-slate-600 mt-0.5">
            Risk scores represent Composite Risk Index (CRI = Fatal &times; 5.0 + Non-Fatal &times; 2.0 + corridor proximity weight) derived from Bengaluru Traffic Police records.
            <span className="text-teal-800 font-medium"> Note: Evaluated on historical spatial observations; no unverified predictive AI claims.</span>
          </p>
        </div>
      </div>

      {/* Risk Zones Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-5">
        {zones.map((zone) => (
          <div
            key={zone.zone_id}
            className="p-3.5 rounded-xl border border-slate-200 bg-slate-50 hover:bg-white hover:border-slate-300 hover:shadow-sm transition"
          >
            <div className="flex items-start justify-between gap-2 mb-2">
              <div>
                <h3 className="text-xs font-bold text-slate-900 uppercase">{zone.zone_name}</h3>
                <span className="text-[10px] text-slate-500 font-mono">ID: {zone.zone_id}</span>
              </div>
              <span className={`px-2 py-0.5 text-[10px] font-bold rounded border ${getRiskBadge(zone.risk_level)}`}>
                {zone.risk_level} (CRI: {zone.composite_risk_score})
              </span>
            </div>

            <div className="grid grid-cols-3 gap-2 text-center text-xs bg-white p-2 rounded-lg border border-slate-200 mb-2 font-mono">
              <div>
                <span className="text-[10px] text-slate-500 block">Total Crashes</span>
                <span className="text-slate-900 font-semibold">{zone.total_crashes}</span>
              </div>
              <div>
                <span className="text-[10px] text-rose-600 block">Fatal Crashes</span>
                <span className="text-rose-600 font-bold">{zone.fatal_crashes}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-500 block">Target TLS</span>
                <span className="text-teal-700 font-semibold">{zone.associated_junction || 'Corridor Link'}</span>
              </div>
            </div>

            <p className="text-[11px] text-slate-600 italic border-l-2 border-slate-300 pl-2">
              &ldquo;{zone.safety_advisory}&rdquo;
            </p>
          </div>
        ))}
      </div>

      {/* Spatial Hotspots Table */}
      {hotspots.length > 0 && (
        <div>
          <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">
            DBSCAN Spatial Hotspot Clusters ({hotspots.length})
          </h3>
          <div className="overflow-x-auto border border-slate-200 rounded-lg">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-slate-100 text-slate-700 text-[10px] uppercase border-b border-slate-200">
                <tr>
                  <th className="py-1.5 px-3">Cluster ID</th>
                  <th className="py-1.5 px-3">Relevance</th>
                  <th className="py-1.5 px-3">Total Crashes</th>
                  <th className="py-1.5 px-3">Fatal</th>
                  <th className="py-1.5 px-3">Severity Score</th>
                  <th className="py-1.5 px-3">Coordinates (Lat, Lon)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-[11px]">
                {hotspots.map((hs) => (
                  <tr key={hs.hotspot_id} className="hover:bg-slate-50">
                    <td className="py-2 px-3 font-semibold text-slate-900">{hs.hotspot_id}</td>
                    <td className="py-2 px-3">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${hs.corridor_relevance === 'CORRIDOR' ? 'bg-teal-50 text-teal-800 border border-teal-200' : 'text-slate-500'}`}>
                        {hs.corridor_relevance}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-slate-700">{hs.total_crashes}</td>
                    <td className="py-2 px-3 text-rose-600 font-bold">{hs.fatal_crashes}</td>
                    <td className="py-2 px-3 text-amber-700 font-bold">{hs.severity_score}</td>
                    <td className="py-2 px-3 text-slate-600">
                      {hs.center_latitude.toFixed(4)}, {hs.center_longitude.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
