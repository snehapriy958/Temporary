import React, { useState, useEffect, useCallback, Suspense } from 'react';
import { Header } from './components/Header';
import { OverviewKPIs } from './components/OverviewKPIs';
import { SimulationControls } from './components/SimulationControls';
import { LiveCorridorView } from './components/LiveCorridorView';
import { SignalStatusPanel } from './components/SignalStatusPanel';
import { EmergencyPanel } from './components/EmergencyPanel';
import { RiskHotspotsPanel } from './components/RiskHotspotsPanel';
import { EmissionAnalytics } from './components/EmissionAnalytics';
import { ControllerComparison } from './components/ControllerComparison';
import { WhatIfScenario } from './components/WhatIfScenario';
import { api } from './services/api';
import { trafficWS } from './services/websocket';
import { snapshotRecoveryManager } from './services/snapshotRecovery';
import { AlertTriangle, X, CheckCircle, ShieldAlert, RefreshCw, Box } from 'lucide-react';

// Lazy-load 3D Corridor chunk on demand
const ThreeCorridorView = React.lazy(() => import('./components/ThreeCorridorView'));

export default function App() {
  // Connection, sync, and system health
  const [wsStatus, setWsStatus] = useState('DISCONNECTED');
  const [syncStatus, setSyncStatus] = useState('DISCONNECTED');
  const [health, setHealth] = useState({ sumo_available: false, sumo_version: '' });
  const [simStatus, setSimStatus] = useState({
    running: false,
    paused: false,
    simulation_time: 0,
    duration: 600,
    mode: 'coordinated',
    seed: 42,
  });

  // Telemetry state
  const [metrics, setMetrics] = useState(null);
  const [junctions, setJunctions] = useState({});
  const [signals, setSignals] = useState({});
  const [emergencies, setEmergencies] = useState(null);
  const [riskData, setRiskData] = useState(null);
  const [compareData, setCompareData] = useState(null);
  const [compareLoading, setCompareLoading] = useState(true);
  const [compareError, setCompareError] = useState(null);

  // Active view tab
  const [activeTab, setActiveTab] = useState('live'); // 'live', 'analytics', 'safety', 'sandbox'

  // Manual Override Modal
  const [isOverrideOpen, setIsOverrideOpen] = useState(false);
  const [overrideJunction, setOverrideJunction] = useState('J2');
  const [overridePhase, setOverridePhase] = useState(0);
  const [overrideConfirmed, setOverrideConfirmed] = useState(false);
  const [overrideLoading, setOverrideLoading] = useState(false);
  const [overrideMessage, setOverrideMessage] = useState({ type: null, text: '' });

  // Initial data loader
  const loadInitialData = useCallback(async () => {
    setCompareLoading(true);
    try {
      const [h, s, m, j, sig, em, r, comp] = await Promise.allSettled([
        api.getHealth(),
        api.getSimulationStatus(),
        api.getTrafficMetrics(),
        api.getTrafficLive(),
        api.getSignals(),
        api.getEmergencies(),
        api.getRisks(),
        api.getExperimentsCompare(),
      ]);

      if (h.status === 'fulfilled') setHealth(h.value);
      if (s.status === 'fulfilled') setSimStatus(s.value);
      if (m.status === 'fulfilled') setMetrics(m.value);
      if (j.status === 'fulfilled' && j.value?.junctions) setJunctions(j.value.junctions);
      if (sig.status === 'fulfilled' && sig.value?.signals) setSignals(sig.value.signals);
      if (em.status === 'fulfilled') setEmergencies(em.value);
      if (r.status === 'fulfilled') setRiskData(r.value);
      if (comp.status === 'fulfilled') {
        setCompareData(comp.value);
        setCompareError(null);
      } else {
        setCompareError(comp.reason?.message || 'Failed to fetch controller benchmark metrics');
      }
    } catch (err) {
      console.warn('Initial data loading warning:', err);
      setCompareError(err.message || 'Failed to initialize dashboard telemetry');
    } finally {
      setCompareLoading(false);
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await api.getSimulationStatus();
      setSimStatus(s);
    } catch (_) {}
  }, []);

  // Set up WebSocket, SnapshotRecoveryManager, and lifecycle listeners
  useEffect(() => {
    // 1. Initialize SnapshotRecoveryManager
    snapshotRecoveryManager.init();

    // 2. Track sync recovery state transitions
    const unsubSyncState = snapshotRecoveryManager.onStateChange((state) => {
      setSyncStatus(state);
    });

    // 3. Track transport-level WebSocket connection status
    const unsubWsStatus = trafficWS.onStatusChange((status) => {
      setWsStatus(status);
    });

    // 4. Track authoritative, synchronized telemetry updates
    const unsubTelemetry = snapshotRecoveryManager.onTelemetry((data) => {
      if (!data) return;

      if (data.simStatus) {
        setSimStatus(data.simStatus);
      } else if (data.status) {
        setSimStatus((prev) => ({
          ...prev,
          running: data.status === 'RUNNING',
          paused: data.status === 'PAUSED',
          simulation_time: data.simulation_time ?? prev.simulation_time,
          mode: data.mode ?? prev.mode,
          run_uuid: data.session_uuid ?? prev.run_uuid,
          sequence_number: data.sequence_number ?? prev.sequence_number,
        }));
      }

      if (data.junctions) setJunctions(data.junctions);
      if (data.signals) setSignals(data.signals);
      if (data.metrics) setMetrics(data.metrics);
      if (data.emergencies) setEmergencies(data.emergencies);
      if (data.risks) setRiskData(data.risks);
      if (data.health) setHealth(data.health);
      if (data.compare) {
        setCompareData(data.compare);
        setCompareError(null);
      }
    });

    // 5. Connect WebSocket transport
    trafficWS.connect();

    return () => {
      unsubSyncState();
      unsubWsStatus();
      unsubTelemetry();
      snapshotRecoveryManager.destroy();
      trafficWS.disconnect();
    };
  }, []);

  // Handle Manual Override submission
  const handleApplyOverride = async (e) => {
    e.preventDefault();
    if (!overrideConfirmed) {
      setOverrideMessage({ type: 'error', text: 'You must confirm the safety override acknowledgment.' });
      return;
    }
    setOverrideLoading(true);
    setOverrideMessage({ type: null, text: '' });
    try {
      const res = await api.overrideSignal(overrideJunction, Number(overridePhase), true);
      setOverrideMessage({ type: 'success', text: res.message || 'Signal phase overridden successfully.' });
      setTimeout(() => {
        setIsOverrideOpen(false);
        setOverrideMessage({ type: null, text: '' });
        setOverrideConfirmed(false);
      }, 1500);
    } catch (err) {
      setOverrideMessage({ type: 'error', text: err.message || 'Manual override failed.' });
    } finally {
      setOverrideLoading(false);
    }
  };

  const handleLaunchScenario = async (params) => {
    try {
      await api.startSimulation(params);
      await refreshStatus();
    } catch (err) {
      alert(`Failed to launch scenario: ${err.message}`);
    }
  };

  return (
    <div className="min-h-screen bg-[#f8fafc] text-slate-900 flex flex-col font-sans">
      {/* Top Header */}
      <Header
        wsStatus={wsStatus}
        health={health}
        simStatus={simStatus}
        onOpenOverride={() => setIsOverrideOpen(true)}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 space-y-6">
        {/* Recovery / Synchronization Status Banner */}
        {syncStatus === 'RECOVERING' && (
          <div className="bg-teal-50 border border-teal-200 text-teal-800 px-4 py-2.5 rounded-lg text-xs flex items-center justify-between shadow-sm animate-pulse">
            <div className="flex items-center gap-2">
              <RefreshCw className="h-4 w-4 animate-spin text-teal-600" />
              <span>Synchronizing corridor telemetry with authoritative backend snapshot...</span>
            </div>
            <span className="font-semibold text-[11px] px-2 py-0.5 rounded bg-teal-100 text-teal-800 border border-teal-300">
              RECOVERING
            </span>
          </div>
        )}

        {syncStatus === 'RECOVERY_ERROR' && (
          <div className="bg-amber-50 border border-amber-200 text-amber-800 px-4 py-2.5 rounded-lg text-xs flex items-center justify-between shadow-sm">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              <span>Corridor synchronization interrupted by network error. Scheduling automatic retry...</span>
            </div>
            <span className="font-semibold text-[11px] px-2 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-300">
              RETRYING
            </span>
          </div>
        )}

        {syncStatus === 'OFFLINE_SYNC_FAILED' && (
          <div className="bg-rose-50 border border-rose-200 text-rose-800 px-4 py-3 rounded-lg text-xs flex flex-wrap items-center justify-between gap-3 shadow-sm">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-rose-600 shrink-0" />
              <span>
                Persistent corridor synchronization failure: Authoritative backend state could not be reconciled after multiple attempts.
              </span>
            </div>
            <button
              onClick={() => snapshotRecoveryManager.manualRetrySync()}
              className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded font-semibold text-xs transition shadow flex items-center gap-1.5"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Retry Synchronization
            </button>
          </div>
        )}

        {/* KPI Overview Ribbon */}
        <OverviewKPIs metrics={metrics} simStatus={simStatus} />

        {/* Simulation Controls Deck */}
        <SimulationControls simStatus={simStatus} onStatusRefresh={refreshStatus} />

        {/* Navigation Tabs */}
        <div className="flex border-b border-slate-200 gap-2">
          <button
            onClick={() => setActiveTab('live')}
            className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition border-b-2 ${
              activeTab === 'live'
                ? 'border-teal-600 text-teal-700 bg-teal-50/60 font-bold'
                : 'border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300'
            }`}
          >
            Live Corridor & Signals
          </button>
          <button
            onClick={() => setActiveTab('analytics')}
            className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition border-b-2 ${
              activeTab === 'analytics'
                ? 'border-teal-600 text-teal-700 bg-teal-50/60 font-bold'
                : 'border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300'
            }`}
          >
            Emissions & Benchmarks
          </button>
          <button
            onClick={() => setActiveTab('safety')}
            className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition border-b-2 ${
              activeTab === 'safety'
                ? 'border-teal-600 text-teal-700 bg-teal-50/60 font-bold'
                : 'border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300'
            }`}
          >
            Accident Hotspots & Risk Zones
          </button>
          <button
            onClick={() => setActiveTab('sandbox')}
            className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition border-b-2 ${
              activeTab === 'sandbox'
                ? 'border-teal-600 text-teal-700 bg-teal-50/60 font-bold'
                : 'border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300'
            }`}
          >
            What-If Sandbox & History
          </button>
          <button
            onClick={() => setActiveTab('3d')}
            className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition border-b-2 flex items-center gap-1.5 ${
              activeTab === '3d'
                ? 'border-teal-600 text-teal-700 bg-teal-50/60 font-bold'
                : 'border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300'
            }`}
          >
            <Box className="h-3.5 w-3.5" />
            <span>3D Digital Twin</span>
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-teal-100 text-teal-800 font-mono border border-teal-200">Phase 3B</span>
          </button>
        </div>

        {/* Tab 1: Live Corridor & Signal Status */}
        {activeTab === 'live' && (
          <div className="space-y-6">
            <LiveCorridorView
              junctions={junctions}
              signals={signals}
              emergencies={emergencies}
              isStale={wsStatus === 'DISCONNECTED'}
            />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <SignalStatusPanel signals={signals} junctions={junctions} />
              <EmergencyPanel emergencies={emergencies} />
            </div>
          </div>
        )}

        {/* Tab 2: Emissions & Controller Benchmarks */}
        {activeTab === 'analytics' && (
          <div className="space-y-6">
            <ControllerComparison
              compareData={compareData}
              isLoading={compareLoading}
              error={compareError}
            />
            <EmissionAnalytics metrics={metrics} />
          </div>
        )}

        {/* Tab 3: Risk Hotspots & Blackspots */}
        {activeTab === 'safety' && (
          <div className="space-y-6">
            <RiskHotspotsPanel riskData={riskData} />
          </div>
        )}

        {/* Tab 4: What-If Sandbox & Experiment Run History */}
        {activeTab === 'sandbox' && (
          <div className="space-y-6">
            <WhatIfScenario onRunScenario={handleLaunchScenario} />
          </div>
        )}

        {/* Tab 5: 3D Corridor Digital Twin (Lazy-loaded) */}
        {activeTab === '3d' && (
          <div className="space-y-6">
            <Suspense fallback={<div className="min-h-[600px] flex items-center justify-center text-slate-500 font-medium">Loading 3D Visualizer...</div>}>
              <ThreeCorridorView onReturnTo2D={() => setActiveTab('live')} />
            </Suspense>
          </div>
        )}
      </main>

      {/* Manual Override Modal */}
      {isOverrideOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm p-4">
          <div className="bg-white border border-slate-200 rounded-2xl max-w-md w-full p-6 shadow-2xl relative text-slate-900">
            <button
              onClick={() => setIsOverrideOpen(false)}
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-700"
            >
              <X className="h-5 w-5" />
            </button>

            <div className="flex items-center gap-2 mb-4">
              <AlertTriangle className="h-6 w-6 text-amber-600" />
              <h2 className="text-base font-bold text-slate-900 uppercase">
                Operator Signal Phase Override
              </h2>
            </div>

            <p className="text-xs text-slate-600 mb-4">
              Intervene directly in signal controllers. Yellow transition clearance and min/max phase boundaries will still be safely enforced by the controller safety shield.
            </p>

            <form onSubmit={handleApplyOverride} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Target Intersection
                </label>
                <select
                  value={overrideJunction}
                  onChange={(e) => setOverrideJunction(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 text-slate-900 rounded-lg px-3 py-2 text-xs focus:ring-1 focus:ring-teal-500 outline-none"
                >
                  <option value="J1">J1: Hosur North Feeder (TLS 1617743335)</option>
                  <option value="J2">J2: Silk Board Central (TLS GS_cluster)</option>
                  <option value="J3">J3: Hosur South Feeder (TLS 6970466614)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Target Signal Phase
                </label>
                <select
                  value={overridePhase}
                  onChange={(e) => setOverridePhase(Number(e.target.value))}
                  className="w-full bg-slate-50 border border-slate-300 text-slate-900 rounded-lg px-3 py-2 text-xs focus:ring-1 focus:ring-teal-500 outline-none"
                >
                  {overrideJunction === 'J2' ? (
                    <>
                      <option value={0}>Phase 0: Hosur Road Arterial Green</option>
                      <option value={1}>Phase 1: Hosur Yellow Clearance</option>
                      <option value={2}>Phase 2: Madiwala Cross Green</option>
                      <option value={3}>Phase 3: Madiwala Yellow Clearance</option>
                    </>
                  ) : (
                    <>
                      <option value={0}>Phase 0: Side Cross Green</option>
                      <option value={1}>Phase 1: Side Cross Yellow Clearance</option>
                      <option value={2}>Phase 2: Hosur Corridor Green</option>
                      <option value={3}>Phase 3: Hosur Corridor Yellow Clearance</option>
                    </>
                  )}
                </select>
              </div>

              <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                <label className="flex items-start gap-2.5 cursor-pointer text-xs text-slate-700">
                  <input
                    type="checkbox"
                    checked={overrideConfirmed}
                    onChange={(e) => setOverrideConfirmed(e.target.checked)}
                    className="mt-0.5 accent-amber-600 rounded"
                  />
                  <span>
                    I confirm this manual signal override is authorized and required for traffic operations.
                  </span>
                </label>
              </div>

              {overrideMessage.text && (
                <div
                  className={`p-3 rounded-lg text-xs flex items-center gap-2 ${
                    overrideMessage.type === 'success'
                      ? 'bg-emerald-50 border border-emerald-200 text-emerald-800'
                      : 'bg-rose-50 border border-rose-200 text-rose-800'
                  }`}
                >
                  {overrideMessage.type === 'success' ? (
                    <CheckCircle className="h-4 w-4 text-emerald-600" />
                  ) : (
                    <AlertTriangle className="h-4 w-4 text-rose-600" />
                  )}
                  <span>{overrideMessage.text}</span>
                </div>
              )}

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setIsOverrideOpen(false)}
                  className="px-4 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold border border-slate-200"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={overrideLoading || !overrideConfirmed}
                  className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs font-semibold shadow-md shadow-amber-600/20"
                >
                  {overrideLoading ? 'Applying...' : 'Confirm & Apply Override'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="border-t border-slate-200 py-4 px-6 text-center text-xs text-slate-500 bg-white">
        Bengaluru Traffic Coordination Center &bull; Silk Board Hosur Road Continuous Corridor &bull; Powered by Eclipse SUMO &amp; FastAPI
      </footer>
    </div>
  );
}
