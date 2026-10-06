import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Camera, Clock3, Cpu, Eye, Gauge, Radio, Timer } from 'lucide-react';

import Header from './Header';
import StatusBadge from './StatusBadge';
import { useNow } from '../hooks/useNow';
import { useSentinelSocket } from '../hooks/useSentinelSocket';
import { formatTime } from '../utils/format';
import { isFresh } from '../utils/status';

interface VisionMetrics {
  status: 'active';
  model: string;
  fps: number;
  latency_ms: number;
  person_detected: boolean;
  confidence: number;
  ts: string;
}

interface DetectionEvent {
  ts: string;
  personDetected: boolean;
  confidence: number;
}

const streamUrl = import.meta.env.VITE_VISION_STREAM_URL
  || `${window.location.protocol}//${window.location.hostname}:8765/stream.mjpg`;
const metricsUrl = new URL(streamUrl);
metricsUrl.pathname = '/metrics';
metricsUrl.search = '';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isVisionMetrics(value: unknown): value is VisionMetrics {
  if (!isRecord(value)) return false;
  const metrics = value;
  return metrics.status === 'active'
    && typeof metrics.model === 'string'
    && typeof metrics.fps === 'number' && Number.isFinite(metrics.fps)
    && typeof metrics.latency_ms === 'number' && Number.isFinite(metrics.latency_ms)
    && typeof metrics.person_detected === 'boolean'
    && typeof metrics.confidence === 'number' && metrics.confidence >= 0 && metrics.confidence <= 1
    && typeof metrics.ts === 'string' && Number.isFinite(Date.parse(metrics.ts));
}

export default function VisionDashboard() {
  const { state, connected } = useSentinelSocket();
  const now = useNow();
  const [metrics, setMetrics] = useState<VisionMetrics | null>(null);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const [streamAvailable, setStreamAvailable] = useState(false);
  const [history, setHistory] = useState<DetectionEvent[]>([]);
  const lastPerson = useRef<boolean | null>(null);
  const lastVisionTimestamp = useRef<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    async function refreshMetrics() {
      try {
        const response = await fetch(metricsUrl, { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error(`Vision service returned HTTP ${response.status}`);
        const data: unknown = await response.json();
        if (!isVisionMetrics(data)) throw new Error('Vision service returned invalid metrics');
        if (!active) return;
        setMetrics(data);
        setMetricsError(null);
      } catch (error) {
        if (!active || controller.signal.aborted) return;
        setMetricsError(error instanceof Error ? error.message : 'Vision service is unavailable');
      }
    }

    void refreshMetrics();
    const timer = window.setInterval(() => void refreshMetrics(), 1_000);
    return () => {
      active = false;
      window.clearInterval(timer);
      controller.abort();
    };
  }, []);

  const metricsAge = metrics === null ? Number.POSITIVE_INFINITY : now - Date.parse(metrics.ts);
  const metricsFresh = metrics !== null && metricsAge >= -5_000 && metricsAge <= 3_000;
  const visionFresh = metricsFresh || (connected && isFresh(state?.vision?.ts, now));
  const personDetected = !visionFresh ? null
    : metricsFresh ? metrics.person_detected : state?.vision?.person_detected ?? null;
  const confidence = !visionFresh ? null
    : metricsFresh ? metrics.confidence : state?.vision?.confidence ?? null;
  const detectionTimestamp = !visionFresh ? null
    : metricsFresh ? metrics.ts : state?.vision?.ts ?? null;
  const model = metricsFresh ? metrics.model : '—';
  const fps = metricsFresh ? metrics.fps : null;
  const latency = metricsFresh ? metrics.latency_ms : null;
  const events = useMemo(() => history.slice().reverse(), [history]);

  useEffect(() => {
    if (personDetected === null || !detectionTimestamp || detectionTimestamp === lastVisionTimestamp.current) return;
    lastVisionTimestamp.current = detectionTimestamp;
    if (personDetected !== lastPerson.current) {
      setHistory(previous => [...previous, {
        ts: detectionTimestamp,
        personDetected,
        confidence: confidence ?? 0,
      }].slice(-20));
      lastPerson.current = personDetected;
    }
  }, [confidence, detectionTimestamp, personDetected]);

  const cameraStatus = visionFresh ? 'ACTIVE' : metricsError ? 'OFFLINE' : 'WAITING';
  const cameraTone = visionFresh ? 'success' : 'neutral';

  return (
    <>
      <Header online={connected && !!state?.system.mqtt_connected} deviceId={state?.telemetry?.device_id}
        now={now} currentPage="vision" />
      <main className="dashboard-shell vision-dashboard">
        <div className="overview-heading flex flex-wrap items-center justify-between gap-4">
          <div><p className="vision-eyebrow">SENTINEL-X / COMPUTER VISION</p><h1>AI Vision</h1></div>
          <div className="vision-status-group">
            <StatusBadge tone={cameraTone} id="vision-dashboard-status">{cameraStatus}</StatusBadge>
            <span className="section-meta">{metricsFresh ? `Updated ${formatTime(metrics?.ts)}` : 'Waiting for camera service'}</span>
          </div>
        </div>

        {metricsError && <div className="connection-notice" role="status">
          <Radio size={17} aria-hidden="true" />
          <span>{metricsError}<small>Start the Python AI service and make its vision stream URL reachable from this browser.</small></span>
        </div>}

        <section aria-labelledby="live-camera-title" className="vision-live-panel panel">
          <div className="panel-heading">
            <h2 id="live-camera-title"><Camera size={17} className="text-cyan-400" aria-hidden="true" />Live webcam</h2>
            <span className={`vision-live-indicator ${streamAvailable && visionFresh ? 'is-live' : ''}`}>
              <span className="status-dot" />{streamAvailable && visionFresh ? 'LIVE' : 'CAMERA FEED'}
            </span>
          </div>
          <div className={`vision-video-frame ${streamAvailable ? 'has-video' : ''}`}>
            <img src={streamUrl} alt="Live USB webcam feed with AI person detection overlay"
              onLoad={() => setStreamAvailable(true)} onError={() => setStreamAvailable(false)} />
            {!streamAvailable && <div className="vision-video-placeholder">
              <span className="vision-placeholder-icon"><Eye size={30} strokeWidth={1.4} aria-hidden="true" /></span>
              <strong>Waiting for the AI camera stream</strong>
              <span>The Python service will publish the annotated USB webcam feed here.</span>
            </div>}
            {streamAvailable && <div className="vision-video-overlay">
              <span><span className="tiny-dot bg-red-400" />REC</span>
              <span>{personDetected ? 'PERSON DETECTED' : 'AREA CLEAR'}</span>
            </div>}
          </div>
          <div className="vision-video-caption">
            <span><Camera size={14} aria-hidden="true" />{metricsFresh ? model : state?.vision?.source || 'USB camera · awaiting connection'}</span>
            <span>{visionFresh ? 'Detection overlay provided by YOLO' : 'AI stream is not active'}</span>
          </div>
        </section>

        <section aria-label="Vision performance metrics" className="vision-metrics-grid">
          <article className="panel vision-metric-card">
            <span className="vision-metric-heading"><Eye size={15} aria-hidden="true" />DETECTION</span>
            <strong className={`vision-metric-value ${personDetected ? 'tone-danger' : personDetected === false ? 'tone-success' : ''}`}>
              {personDetected === null ? '—' : personDetected ? 'PERSON' : 'CLEAR'}
            </strong>
          </article>
          <article className="panel vision-metric-card">
            <span className="vision-metric-heading"><Gauge size={15} aria-hidden="true" />CONFIDENCE</span>
            <strong className="vision-metric-value">{confidence === null ? '—' : `${Math.round(confidence * 100)}%`}</strong>
          </article>
          <article className="panel vision-metric-card">
            <span className="vision-metric-heading"><Activity size={15} aria-hidden="true" />INFERENCE FPS</span>
            <strong className="vision-metric-value">{fps === null ? '—' : fps.toFixed(1)}</strong>
          </article>
          <article className="panel vision-metric-card">
            <span className="vision-metric-heading"><Timer size={15} aria-hidden="true" />LATENCY</span>
            <strong className="vision-metric-value">{latency === null ? '—' : `${latency.toFixed(1)} ms`}</strong>
          </article>
          <article className="panel vision-metric-card">
            <span className="vision-metric-heading"><Cpu size={15} aria-hidden="true" />MODEL</span>
            <strong className="vision-metric-value vision-model-value">{model}</strong>
          </article>
          <article className="panel vision-metric-card">
            <span className="vision-metric-heading"><Radio size={15} aria-hidden="true" />STATUS</span>
            <strong className={`vision-metric-value tone-${cameraTone}`}><span className="status-dot" />{cameraStatus}</strong>
          </article>
        </section>

        <section className="panel vision-history-panel" aria-labelledby="vision-history-title">
          <div className="panel-heading">
            <h2 id="vision-history-title"><Clock3 size={17} className="text-cyan-400" aria-hidden="true" />Detection history</h2>
            <span className="section-meta">State changes observed in this session</span>
          </div>
          {events.length === 0 ? <div className="vision-history-empty">
            <Activity size={21} strokeWidth={1.4} aria-hidden="true" />
            <span>Detection events will appear when the camera service connects.</span>
          </div> : <ul className="vision-history-list">
            {events.map((event, index) => <li key={`${event.ts}-${index}`}>
              <span className={`vision-history-icon ${event.personDetected ? 'tone-danger' : 'tone-success'}`}>
                <Eye size={15} aria-hidden="true" />
              </span>
              <span className="vision-history-description">
                <strong>{event.personDetected ? 'Person detected' : 'No person'}</strong>
                {event.personDetected && <small>{Math.round(event.confidence * 100)}% confidence</small>}
              </span>
              <time dateTime={event.ts}>{formatTime(event.ts)}</time>
            </li>)}
          </ul>}
        </section>

        <footer className="dashboard-footer flex flex-wrap items-center justify-between gap-3">
          <span><span className={`tiny-dot ${visionFresh ? 'bg-emerald-400' : 'bg-slate-500'}`} />
            {visionFresh ? 'VISION SERVICE ACTIVE' : 'WAITING FOR VISION SERVICE'}</span>
          <span>AI Vision<span className="footer-divider">/</span>SENTINEL-X</span>
        </footer>
      </main>
    </>
  );
}
