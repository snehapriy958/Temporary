import React from 'react';
import { Box, Layers } from 'lucide-react';

export function Corridor3DLoadingSkeleton() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[600px] w-full bg-white rounded-xl border border-slate-200 p-8 text-center relative overflow-hidden">
      {/* Background grid effect */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#e2e8f080_1px,transparent_1px),linear-gradient(to_bottom,#e2e8f080_1px,transparent_1px)] bg-[size:40px_40px] pointer-events-none" />

      <div className="relative z-10 flex flex-col items-center space-y-4">
        <div className="relative">
          <div className="w-16 h-16 rounded-2xl bg-teal-50 border border-teal-200 flex items-center justify-center">
            <Box className="w-8 h-8 text-teal-600 animate-spin" style={{ animationDuration: '6s' }} />
          </div>
          <div className="absolute -top-1 -right-1 w-6 h-6 rounded-full bg-purple-100 border border-purple-200 flex items-center justify-center">
            <Layers className="w-3.5 h-3.5 text-purple-600" />
          </div>
        </div>

        <div className="space-y-1">
          <h3 className="text-base font-bold text-slate-900">
            Initializing Bengaluru Silk Board 3D Twin
          </h3>
          <p className="text-xs text-slate-500 max-w-sm">
            Triangulating 306 corridor edges, J1–J2–J3 junction conflict zones, and grade-separated flyover decks...
          </p>
        </div>

        <div className="w-48 h-1.5 bg-slate-100 rounded-full overflow-hidden border border-slate-200">
          <div className="h-full bg-gradient-to-r from-teal-500 to-emerald-500 w-2/3 animate-pulse rounded-full" />
        </div>

        <div className="flex items-center gap-4 text-[11px] text-slate-500 pt-2 font-mono">
          <span>Three.js v0.187</span>
          <span>•</span>
          <span>React Three Fiber</span>
          <span>•</span>
          <span>3.20m SUMO Lanes</span>
        </div>
      </div>
    </div>
  );
}
