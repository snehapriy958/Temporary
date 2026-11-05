import React from 'react';
import { Wind, Fuel, BarChart3 } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';

export function EmissionAnalytics({ metrics, history = [] }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <Wind className="h-5 w-5 text-teal-600" />
          <h2 className="text-sm font-bold tracking-wide text-slate-900 uppercase">
            Corridor Emissions & Environmental Analytics
          </h2>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span>CO₂: kg</span>
          <span>&bull;</span>
          <span>NOx: g</span>
          <span>&bull;</span>
          <span>Fuel: Est. Liters (ρ = 0.75 kg/L)</span>
        </div>
      </div>

      {/* Primary KPI cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5">
          <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
            <span>Cumulative CO₂</span>
            <Wind className="h-4 w-4 text-teal-600" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-900">
            {metrics?.total_co2_kg == null ? '—' : Number(metrics.total_co2_kg).toFixed(4)} <span className="text-xs text-slate-500">kg</span>
          </div>
        </div>

        <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5">
          <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
            <span>Cumulative NOx</span>
            <Wind className="h-4 w-4 text-purple-600" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-900">
            {metrics?.total_nox_g == null ? '—' : Number(metrics.total_nox_g).toFixed(4)} <span className="text-xs text-slate-500">g</span>
          </div>
          <p className="text-[11px] text-slate-500 mt-1">
            HBEFA 3.1 vehicle emission model
          </p>
        </div>

        <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5">
          <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
            <span>Estimated Fuel Volume</span>
            <Fuel className="h-4 w-4 text-purple-600" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-900">
            {metrics?.total_fuel_liters == null ? '—' : Number(metrics.total_fuel_liters).toFixed(4)} <span className="text-xs text-slate-500">L</span>
          </div>
          <div className="mt-1 space-y-0.5">
            <p className="text-[10px] text-slate-500">
              Gasoline equivalent (ρ = 0.75 kg/L)
            </p>
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="h-56 w-full">
        <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">
          Real-Time CO₂ & Fuel Accumulation Curve
        </h3>
        {history.length < 2 ? (
          <div className="h-full flex items-center justify-center text-xs text-slate-500 italic border border-dashed border-slate-200 rounded-lg">
            {history.length === 0
              ? 'Awaiting simulation telemetry data points...'
              : 'One current snapshot is available; the accumulation curve fills during a live run.'}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={history} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="co2Grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#0d9488" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#0d9488" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="time" stroke="#64748b" tick={{ fontSize: 10, fill: '#64748b' }} unit="s" />
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
              <Area
                type="monotone"
                dataKey="co2_kg"
                name="CO₂ (kg)"
                stroke="#0d9488"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#co2Grad)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
