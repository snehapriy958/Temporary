import React from 'react';
import { Car, Gauge, Hourglass, GitCommit, Wind, Fuel, MapPin } from 'lucide-react';

export function OverviewKPIs({ metrics, simStatus }) {
  const isRunning = simStatus?.running && !simStatus?.paused;
  const isCompletedSnapshot = !isRunning && !simStatus?.paused && metrics != null;

  const kpis = [
    {
      title: 'Intersections',
      value: '3 / 3',
      sub: 'J1, J2 (Silk Board), J3',
      icon: MapPin,
      color: 'text-teal-600',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
    {
      title: 'Active Vehicles',
      value: metrics?.total_vehicles == null ? '—' : metrics.total_vehicles,
      sub: 'Vehicles currently in network',
      icon: Car,
      color: 'text-teal-700',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
    {
      title: 'Throughput',
      value: metrics?.throughput_vehicles == null ? '—' : metrics.throughput_vehicles,
      sub: 'Completed corridor trips',
      icon: GitCommit,
      color: 'text-emerald-600',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
    {
      title: 'Average Speed',
      value: metrics?.mean_speed_kmh == null ? '—' : `${Number(metrics.mean_speed_kmh).toFixed(2)} km/h`,
      sub: 'Corridor progression',
      icon: Gauge,
      color: 'text-purple-600',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
    {
      title: 'Mean Snapshot Wait',
      value: metrics?.mean_instantaneous_waiting_time_s == null
        ? '—'
        : `${Number(metrics.mean_instantaneous_waiting_time_s).toFixed(2)} s`,
      sub: 'Run mean of per-step sum of approach wait (s)',
      detail: metrics?.cumulative_delay_veh_s == null
        ? null
        : `${Number(metrics.cumulative_delay_veh_s).toFixed(2)} veh·s`,
      icon: Hourglass,
      color: 'text-amber-600',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
    {
      title: 'CO₂ Emissions',
      value: metrics?.total_co2_kg == null ? '—' : `${Number(metrics.total_co2_kg).toFixed(4)} kg`,
      sub: `NOx: ${metrics?.total_nox_g == null ? '—' : `${Number(metrics.total_nox_g).toFixed(4)} g`}`,
      icon: Wind,
      color: 'text-teal-600',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
    {
      title: 'Estimated Fuel Volume',
      value: metrics?.total_fuel_liters == null ? '—' : `${Number(metrics.total_fuel_liters).toFixed(4)} L`,
      sub: 'Gasoline equivalent',
      subTitle: 'Estimated gasoline equivalent using ρ = 0.75 kg/L',
      icon: Fuel,
      color: 'text-purple-600',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
  ];

  return (
    <>
    {isCompletedSnapshot && (
      <p className="mb-2 rounded-md border border-slate-200 bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600">
        Last completed simulation snapshot · values are not live measurements
      </p>
    )}
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-3">
      {kpis.map((kpi, index) => {
        const Icon = kpi.icon;
        return (
          <div
            key={index}
            className={`min-w-0 p-3.5 rounded-xl border ${kpi.border} ${kpi.bg} shadow-sm flex flex-col justify-between transition hover:border-slate-300 hover:shadow`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <span className="min-w-0 text-[11px] font-semibold uppercase tracking-wider text-slate-500 break-words">
                {kpi.title}
              </span>
              <Icon className={`h-4 w-4 ${kpi.color}`} />
            </div>
            <div>
              <div className="break-words text-xl font-bold tracking-tight text-slate-900 font-mono">
                {kpi.value}
              </div>
              <p title={kpi.subTitle || kpi.sub} className="text-[11px] leading-snug text-slate-500 whitespace-normal break-words mt-0.5">
                {kpi.sub}
              </p>
              {kpi.detail && (
                <div className="mt-1 rounded bg-amber-50 px-1.5 py-1 text-[10px] leading-snug text-amber-800 break-words">
                  <span className="font-semibold">Cumulative Delay</span>
                  <p>{kpi.detail}</p>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
    </>
  );
}
