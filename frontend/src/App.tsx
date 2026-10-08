import { Activity, Droplets, Radio, Thermometer, Wind } from 'lucide-react';
import { lazy, Suspense } from 'react';

import AlertsPanel from './components/AlertsPanel';
import CommandPanel from './components/CommandPanel';
import Header from './components/Header';
import SensorCard from './components/SensorCard';
import StatusBadge from './components/StatusBadge';
import SystemStatus from './components/SystemStatus';
import { useNow } from './hooks/useNow';
import { useSentinelSocket } from './hooks/useSentinelSocket';
import { formatNumber, formatTime } from './utils/format';
import { isFresh } from './utils/status';
import type { Tone } from './utils/status';

const SensorChart = lazy(() => import('./components/SensorChart'));
const EnvironmentDashboard = lazy(() => import('./components/EnvironmentDashboard'));
const VisionDashboard = lazy(() => import('./components/VisionDashboard'));

export default function App() {
  const pathname = window.location.pathname.replace(/\/+$/, '');
  if (pathname === '/vision') {
    return <Suspense fallback={<section className="panel chart-loading">Loading AI Vision dashboard…</section>}>
      <VisionDashboard />
    </Suspense>;
  }
  if (pathname === '/environment') {
    return <Suspense fallback={<section className="panel chart-loading">Loading AI Environment dashboard…</section>}>
      <EnvironmentDashboard />
    </Suspense>;
  }
  return <OverviewDashboard />;
}

function OverviewDashboard() {
  const { state, connected, error, receivedAt } = useSentinelSocket();
  const now = useNow();
  const online = connected && !!state?.system.mqtt_connected;
  const telemetry = state?.telemetry;
  const telemetryFresh = online && isFresh(telemetry?.ts, now);
  const sensorFresh = telemetryFresh && state?.device?.online !== false;
  const presenceReady = typeof telemetry?.presence === 'boolean';
  const distanceReady = telemetry?.distance_sensor === true;
  const visionFresh = online && isFresh(state?.vision?.ts, now);
  const anomalyFresh = online && isFresh(state?.anomaly?.ts, now);

  let safety: { label: string; tone: Tone; detail: string };
  if (!online) safety = { label: 'OFFLINE', tone: 'neutral', detail: 'Waiting for a live connection' };
  else if (visionFresh && state?.vision?.person_detected) safety = { label: 'CRITICAL', tone: 'danger', detail: 'Human presence detected' };
  else if (anomalyFresh && state?.anomaly?.ready && state.anomaly.anomaly) safety = { label: 'WARNING', tone: 'warning', detail: 'Environmental anomaly detected' };
  else if (anomalyFresh && state?.anomaly?.ready === false) safety = { label: 'CALIBRATING', tone: 'warning', detail: 'Learning the environmental baseline' };
  else if (!telemetryFresh || !visionFresh || !anomalyFresh) safety = { label: 'WAITING', tone: 'neutral', detail: 'Awaiting current sensor and AI results' };
  else safety = { label: 'SAFE', tone: 'success', detail: 'No active AI detections' };

  const readingDetail = !telemetry ? 'Awaiting telemetry' : !online ? 'Last known reading' : !telemetryFresh ? 'Stale reading' : 'Live reading';
  return (
    <>
      <Header online={online} deviceId={telemetry?.device_id} now={now} currentPage="overview" />
      <main id="overview" className="dashboard-shell">
        <div className="overview-heading flex flex-wrap items-center justify-between gap-4">
          <div><h1>Security overview</h1></div>
          <div className="safety-summary"><StatusBadge tone={safety.tone} id="safety-status">{safety.label}</StatusBadge><p>{safety.detail}</p></div>
        </div>

        {(error || (connected && !online)) && <div className="connection-notice" role="status">
          <Radio size={17} aria-hidden="true" /><span>{error || 'MQTT is offline. Awaiting broker connection.'}
            {state?.telemetry && <small>Last known data remains visible. Alarm controls require a live connection.</small>}</span>
        </div>}
        <SystemStatus state={state} connected={connected} now={now} />

        <section aria-labelledby="environment-title" id="environment">
          <div className="section-heading environment-heading"><h2 id="environment-title"><Activity size={16} aria-hidden="true" />Environment</h2>
            <span className="section-meta">{telemetry?.device_id || 'Awaiting sensor node'} · {formatTime(telemetry?.ts)}</span></div>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <SensorCard title="Temperature" value={formatNumber(telemetry?.temperature)} unit="°C" icon={Thermometer} detail={readingDetail} live={telemetryFresh} id="temperature-value" />
            <SensorCard title="Humidity" value={formatNumber(telemetry?.humidity)} unit="%" icon={Droplets} detail={readingDetail} live={telemetryFresh} id="humidity-value" />
            <SensorCard title="Gas" value={formatNumber(telemetry?.gas, true)} unit="raw" icon={Wind} detail={telemetryFresh ? 'Raw sensor value' : readingDetail} live={telemetryFresh} id="gas-value" />
            <SensorCard title="Distance" value={!sensorFresh || !distanceReady ? 'UNKNOWN' : telemetry?.distance_cm == null ? 'NO ECHO' : formatNumber(telemetry.distance_cm)} unit={sensorFresh && distanceReady && telemetry?.distance_cm != null ? 'cm' : undefined} icon={Radio} detail={!sensorFresh ? readingDetail : !distanceReady ? 'Awaiting ultrasonic data' : telemetry?.distance_cm == null ? 'No return echo' : 'Ultrasonic distance'} live={sensorFresh && distanceReady} id="distance-value" />
            <SensorCard title="Presence" value={!sensorFresh || !presenceReady ? 'UNKNOWN' : telemetry?.presence === true ? 'OUI' : 'NON'} icon={Activity} detail={!sensorFresh ? state?.device?.online === false ? 'Sensor node offline' : readingDetail : !presenceReady ? 'Awaiting presence sensor' : telemetry?.presence === true ? 'Presence sensor active' : 'Presence sensor inactive'} live={sensorFresh && presenceReady} motion={sensorFresh && presenceReady && telemetry?.presence === true} id="presence-value" />
          </div>
        </section>

        <Suspense fallback={<section className="panel chart-loading" aria-label="Environmental trends">Loading environmental trends…</section>}>
          <SensorChart history={state?.history ?? []} live={telemetryFresh} />
        </Suspense>

        <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-3">
          <div className="min-w-0 lg:col-span-2"><AlertsPanel alerts={state?.alerts ?? []} /></div>
          <CommandPanel enabled={online} />
        </div>

        <footer className="dashboard-footer flex flex-wrap items-center justify-between gap-3">
          <span><span className={`tiny-dot ${connected ? 'bg-cyan-400' : 'bg-slate-500'}`} />{connected ? 'LIVE DATA CONNECTION' : 'RECONNECTING TO BACKEND'}</span>
          <span>Last received {formatTime(receivedAt)}<span className="footer-divider">/</span>SENTINEL-X</span>
        </footer>
      </main>
    </>
  );
}
