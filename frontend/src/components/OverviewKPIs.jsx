import React from 'react';
import { Car, Gauge, Hourglass, GitCommit, Wind, Fuel, MapPin } from 'lucide-react';

export function OverviewKPIs({ metrics, simStatus }) {
  const isRunning = simStatus?.running && !simStatus?.paused;

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
      value: metrics?.total_vehicles ?? 0,
      sub: isRunning ? 'Real-time observation' : 'Idle / waiting',
      icon: Car,
      color: 'text-teal-700',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
    {
      title: 'Throughput',
      value: metrics?.throughput_vehicles ?? 0,
      sub: 'Completed corridor trips',
      icon: GitCommit,
      color: 'text-emerald-600',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
    {
      title: 'Average Speed',
      value: `${metrics?.mean_speed_kmh ?? 0} km/h`,
      sub: 'Corridor progression',
      icon: Gauge,
      color: 'text-purple-600',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
    {
      title: 'Average Wait Time',
      value: `${metrics?.total_corridor_waiting_time_s ?? 0}s`,
      sub: `Mean Queue: ${metrics?.mean_corridor_queue ?? 0} veh`,
      icon: Hourglass,
      color: 'text-amber-600',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
    {
      title: 'CO₂ Emissions',
      value: `${metrics?.total_co2_kg ?? 0} kg`,
      sub: `NOx: ${metrics?.total_nox_g ?? 0} g`,
      icon: Wind,
      color: 'text-teal-600',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
    {
      title: 'Estimated Fuel Volume',
      value: `${metrics?.total_fuel_liters ?? 0} L`,
      sub: 'Gasoline equivalent (ρ = 0.75 kg/L)',
      icon: Fuel,
      color: 'text-purple-600',
      border: 'border-slate-200',
      bg: 'bg-white',
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
      {kpis.map((kpi, index) => {
        const Icon = kpi.icon;
        return (
          <div
            key={index}
            className={`p-3.5 rounded-xl border ${kpi.border} ${kpi.bg} shadow-sm flex flex-col justify-between transition hover:border-slate-300 hover:shadow`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                {kpi.title}
              </span>
              <Icon className={`h-4 w-4 ${kpi.color}`} />
            </div>
            <div>
              <div className="text-xl font-bold tracking-tight text-slate-900 font-mono">
                {kpi.value}
              </div>
              <p className="text-[11px] text-slate-500 truncate mt-0.5">
                {kpi.sub}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
