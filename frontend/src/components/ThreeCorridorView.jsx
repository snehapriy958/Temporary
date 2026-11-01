import React, { useState, Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import {
  Compass,
  Layers,
  Info,
  Maximize2,
  ArrowLeft,
  Eye,
  EyeOff,
  Navigation,
  ShieldAlert,
} from 'lucide-react';

import { CorridorScene, CAMERA_PRESETS } from './ThreeCorridor/CorridorScene';
import { CorridorErrorBoundary } from './ThreeCorridor/CorridorErrorBoundary';
import { Corridor3DLoadingSkeleton } from './ThreeCorridor/Corridor3DLoadingSkeleton';

export default function ThreeCorridorView({ onReturnTo2D }) {
  const [activePreset, setActivePreset] = useState('overview');
  const [isBannerOpen, setIsBannerOpen] = useState(true);
  const [layerVisibility, setLayerVisibility] = useState({
    ground: true,
    flyover: true,
    underpass: true,
    dividers: true,
    pillars: true,
    junctions: true,
    markers: true,
  });
  const [showLayerMenu, setShowLayerMenu] = useState(false);

  const toggleLayer = (key) => {
    setLayerVisibility(prev => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="space-y-4">
      {/* Top Controls Toolbar */}
      <div className="bg-white border border-slate-200 rounded-xl p-3 flex flex-wrap items-center justify-between gap-3 shadow-sm">
        {/* Left: Camera Presets */}
        <div className="flex items-center gap-1.5 overflow-x-auto">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 mr-2 flex items-center gap-1.5">
            <Compass className="h-3.5 w-3.5 text-teal-600" />
            Camera:
          </span>
          {Object.entries(CAMERA_PRESETS).map(([key, preset]) => {
            const isActive = activePreset === key;
            return (
              <button
                key={key}
                onClick={() => setActivePreset(key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition flex items-center gap-1.5 ${
                  isActive
                    ? 'bg-teal-50 text-teal-800 border border-teal-300 shadow-sm font-semibold'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-200'
                }`}
                title={preset.desc}
              >
                <Navigation className={`h-3 w-3 ${isActive ? 'text-teal-600' : 'text-slate-400'}`} />
                {preset.label}
              </button>
            );
          })}
        </div>

        {/* Right: Layer Toggles & 2D Return */}
        <div className="flex items-center gap-2 relative">
          <div className="relative">
            <button
              onClick={() => setShowLayerMenu(!showLayerMenu)}
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200 flex items-center gap-1.5 transition"
            >
              <Layers className="h-3.5 w-3.5 text-purple-600" />
              <span>Layers</span>
            </button>

            {showLayerMenu && (
              <div className="absolute right-0 mt-2 w-56 rounded-xl bg-white border border-slate-200 p-2 shadow-xl z-50 text-xs space-y-1">
                <div className="px-2 py-1 text-[11px] font-semibold text-slate-500 border-b border-slate-200 uppercase tracking-wider">
                  Corridor Layer Filter
                </div>
                {[
                  { key: 'ground', label: 'Ground Roads' },
                  { key: 'flyover', label: 'Elevated Flyovers (+8.0m)' },
                  { key: 'underpass', label: 'Depressed Underpasses (-4.5m)' },
                  { key: 'junctions', label: 'Junction Conflict Areas' },
                  { key: 'dividers', label: 'Dashed Lane Dividers' },
                  { key: 'pillars', label: 'Concrete Piers / Pillars' },
                  { key: 'markers', label: '3D Junction Labels' },
                ].map(({ key, label }) => (
                  <button
                    key={key}
                    onClick={() => toggleLayer(key)}
                    className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg hover:bg-slate-50 text-slate-700 transition"
                  >
                    <span>{label}</span>
                    {layerVisibility[key] ? (
                      <Eye className="h-3.5 w-3.5 text-teal-600" />
                    ) : (
                      <EyeOff className="h-3.5 w-3.5 text-slate-400" />
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {onReturnTo2D && (
            <button
              onClick={onReturnTo2D}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-teal-600 hover:bg-teal-500 text-white transition shadow-sm flex items-center gap-1.5"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              <span>Return to 2D Dashboard</span>
            </button>
          )}
        </div>
      </div>

      {/* 3D WebGL Canvas Viewport */}
      <div className="relative w-full h-[660px] rounded-xl overflow-hidden border border-slate-200 bg-[#090d16] shadow-md">
        {/* Floating Elevation Provenance Banner */}
        {isBannerOpen && (
          <div className="absolute top-3 left-3 right-3 sm:right-auto sm:max-w-xl z-20 bg-white/95 border border-amber-300 rounded-xl p-3 shadow-lg backdrop-blur-md text-slate-900">
            <div className="flex items-start gap-2.5 text-xs">
              <ShieldAlert className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
              <div className="flex-1 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-amber-800 tracking-wide text-[11px] uppercase">
                    ASSUMED_ESTIMATE • Provenance Notice
                  </span>
                  <button
                    onClick={() => setIsBannerOpen(false)}
                    className="text-slate-400 hover:text-slate-700 text-xs px-1"
                  >
                    ✕
                  </button>
                </div>
                <p className="text-[11px] text-slate-700 leading-relaxed">
                  Vertical elevations (Flyover <span className="font-mono text-teal-700 font-semibold">+8.0m</span>, Underpass{' '}
                  <span className="font-mono text-teal-700 font-semibold">-4.5m</span>) are illustrative visualization
                  approximations based on IRC:54-1974 clearance norms. Ground truth horizontal road geometry is
                  extracted directly from Eclipse SUMO <code className="text-teal-800 bg-slate-100 px-1 py-0.5 rounded font-mono border border-slate-200">silk_board.net.xml</code>.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Orbit Controls Guidance Overlay (Bottom-Left) */}
        <div className="absolute bottom-3 left-3 z-20 bg-white/90 border border-slate-200 rounded-lg px-3 py-2 text-[11px] text-slate-700 backdrop-blur-sm pointer-events-none shadow-sm">
          <div className="flex items-center gap-2 font-mono text-slate-700">
            <span>🖱️ Left-Click: Rotate</span>
            <span>•</span>
            <span>Right-Click: Pan</span>
            <span>•</span>
            <span>Scroll: Zoom</span>
          </div>
        </div>

        {/* Corridor Technical Specs Overlay (Bottom-Right) */}
        <div className="absolute bottom-3 right-3 z-20 bg-white/90 border border-slate-200 rounded-lg px-3 py-2 text-[11px] text-slate-700 backdrop-blur-sm pointer-events-none hidden sm:block shadow-sm">
          <div className="flex items-center gap-3 font-mono">
            <span>306 Edges</span>
            <span>•</span>
            <span>490 Lanes (3.20m width)</span>
            <span>•</span>
            <span className="text-teal-700 font-semibold">J1–J2–J3 Corridor</span>
          </div>
        </div>

        {/* React Three Fiber Scene with ErrorBoundary and Suspense */}
        <CorridorErrorBoundary onReturnTo2D={onReturnTo2D}>
          <Suspense fallback={<Corridor3DLoadingSkeleton />}>
            <Canvas
              shadows
              camera={{
                position: CAMERA_PRESETS.overview.position,
                fov: 45,
                near: 1.0,
                far: 3500,
              }}
              gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
            >
              <CorridorScene
                activePreset={activePreset}
                onSelectPreset={setActivePreset}
                layerVisibility={layerVisibility}
              />
            </Canvas>
          </Suspense>
        </CorridorErrorBoundary>
      </div>
    </div>
  );
}
