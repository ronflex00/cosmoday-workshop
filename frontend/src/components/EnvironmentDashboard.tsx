import { useMemo } from 'react';
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, BrainCircuit, ChartNoAxesCombined,
  Clock3, Droplets, Gauge, Thermometer, TriangleAlert, Wind,
} from 'lucide-react';
import {
  Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

import Header from './Header';
import EnvironmentInterpretationPanel from './EnvironmentInterpretationPanel';
import StatusBadge from './StatusBadge';
import { useNow } from '../hooks/useNow';
import { useSentinelSocket } from '../hooks/useSentinelSocket';
import { formatNumber, formatTime } from '../utils/format';
import { isFresh } from '../utils/status';
import { analyzeEnvironment, environmentIntelligenceEnabled } from '../utils/environmentAnalysis';
import type { AnomalyResult, SensorTelemetry } from '../types/sentinel';

type FeatureKey = 'temperature' | 'humidity' | 'gas';

const featureCharts: {
  key: FeatureKey;
  title: string;
  unit: string;
  color: string;
  Icon: typeof Thermometer;
}[] = [
  { key: 'temperature', title: 'Temperature', unit: '°C', color: '#22d3ee', Icon: Thermometer },
  { key: 'humidity', title: 'Humidity', unit: '%', color: '#818cf8', Icon: Droplets },
  { key: 'gas', title: 'Gas', unit: 'raw', color: '#fbbf24', Icon: Wind },
];

function getTrend(points: SensorTelemetry[], key: FeatureKey) {
  const recent = points.slice(-6);
  if (recent.length < 2) return null;
  const change = recent[recent.length - 1][key] - recent[0][key];
  return { change, direction: change > 0 ? 'up' : change < 0 ? 'down' : 'steady' } as const;
}

function modelName(anomaly: AnomalyResult | null): string {
  if (!anomaly) return '—';
  return anomaly.model.toLowerCase() === 'isolation_forest'
    ? 'Isolation Forest' : anomaly.model.replaceAll('_', ' ');
}

function AnomalyScoreChart({ results, live }: {
  results: AnomalyResult[];
  live: boolean;
}) {
  const data = useMemo(() => results.slice(-120).filter(result => result.score !== null), [results]);

  return (
    <article className={`panel environment-score-chart ${!live ? 'data-muted' : ''}`}>
      <div className="chart-heading">
        <h3><span className="tiny-dot bg-cyan-400" />Isolation Forest score</h3>
        <span className="section-meta">{data.length} evaluated samples</span>
      </div>
      {data.length === 0 ? <div className="environment-chart-empty">
        <ChartNoAxesCombined size={23} strokeWidth={1.4} aria-hidden="true" />
        <span>Scores appear once the model finishes calibration.</span>
      </div> : <div className="environment-score-plot">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <AreaChart data={data} margin={{ top: 14, right: 12, left: -18, bottom: 0 }} accessibilityLayer>
            <defs>
              <linearGradient id="environment-score-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.24} />
                <stop offset="100%" stopColor="#22d3ee" stopOpacity={0.015} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="#344a65" strokeDasharray="3 4" />
            <XAxis dataKey="ts" tickFormatter={formatTime}
              tick={{ fill: '#b2c3d8', fontSize: 10 }} tickLine={false} axisLine={false}
              minTickGap={44} interval="preserveStartEnd" />
            <YAxis domain={['auto', 'auto']} tick={{ fill: '#b2c3d8', fontSize: 10 }}
              tickLine={false} axisLine={false} width={48} />
            <ReferenceLine y={0} stroke="#ff9b79" strokeDasharray="5 4" />
            <Tooltip content={({ active, payload, label }) => {
              const point = payload?.[0]?.payload as AnomalyResult | undefined;
              return !active || !point || point.score === null ? null : (
                <div className="chart-tooltip">
                  <span>{formatTime(String(label))}</span>
                  <strong style={{ color: point.anomaly ? '#ff8388' : '#67dfa7' }}>
                    {formatNumber(point.score, true)} · {point.anomaly ? 'ANOMALY' : 'NORMAL'}
                  </strong>
                </div>
              );
            }} />
            <Area type="monotone" dataKey="score" stroke="#22d3ee" strokeWidth={2}
              fill="url(#environment-score-fill)" isAnimationActive={false}
              dot={data.length === 1 ? { r: 3, fill: '#22d3ee' } : false}
              activeDot={{ r: 4, stroke: '#0f1b2d', strokeWidth: 2 }} />
          </AreaChart>
        </ResponsiveContainer>
      </div>}
      <p className="environment-chart-note">Dashed zero line is the classifier boundary used by the model.</p>
    </article>
  );
}

function SensorTrendChart({ telemetry, metric }: {
  telemetry: SensorTelemetry[];
  metric: (typeof featureCharts)[number];
}) {
  const points = useMemo(() => telemetry.slice(-120), [telemetry]);
  const { Icon } = metric;
  const latest = points.at(-1);
  const trend = getTrend(points, metric.key);
  const TrendIcon = !trend || trend.direction === 'steady' ? ArrowRight
    : trend.direction === 'up' ? ArrowUpRight : ArrowDownRight;

  return (
    <article className="panel environment-trend-chart" aria-label={`${metric.title} time series`}>
      <div className="chart-heading">
        <h3><Icon size={15} aria-hidden="true" />{metric.title}</h3>
        <span className={`environment-trend-direction ${trend?.direction ?? ''}`} aria-label={
          !trend ? 'Trend unavailable' : trend.direction === 'steady' ? 'No change' : `Trending ${trend.direction}`}>
          <TrendIcon size={17} aria-hidden="true" />
          {trend ? `${trend.change > 0 ? '+' : ''}${formatNumber(trend.change, true)}` : '—'}
        </span>
      </div>
      <p className="environment-trend-latest">
        {formatNumber(latest?.[metric.key], metric.key === 'gas')}<small>{metric.unit}</small>
      </p>
      {points.length < 2 ? <div className="environment-trend-empty">Waiting for more sensor samples</div>
        : <div className="environment-sensor-plot">
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            <AreaChart data={points} margin={{ top: 8, right: 4, left: -22, bottom: 0 }} accessibilityLayer>
              <defs>
                <linearGradient id={`environment-fill-${metric.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={metric.color} stopOpacity={0.2} />
                  <stop offset="100%" stopColor={metric.color} stopOpacity={0.01} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="#344a65" strokeDasharray="3 4" />
              <XAxis dataKey="ts" tickFormatter={formatTime} hide />
              <YAxis domain={['auto', 'auto']} tick={{ fill: '#b2c3d8', fontSize: 9 }}
                tickLine={false} axisLine={false} width={47} />
              <Tooltip content={({ active, payload, label }) => typeof payload?.[0]?.value !== 'number' || !active
                ? null : <div className="chart-tooltip"><span>{formatTime(String(label))}</span>
                  <strong style={{ color: metric.color }}>
                    {formatNumber(payload[0].value, true)} {metric.unit}
                  </strong></div>} />
              <Area type="monotone" dataKey={metric.key} stroke={metric.color} strokeWidth={2}
                fill={`url(#environment-fill-${metric.key})`} isAnimationActive={false}
                dot={false} activeDot={{ r: 4, stroke: '#0f1b2d', strokeWidth: 2 }} />
            </AreaChart>
          </ResponsiveContainer>
        </div>}
      <p className="environment-trend-footnote">
        {points.length} readings · direction compares the latest six samples
      </p>
    </article>
  );
}

export default function EnvironmentDashboard() {
  const { state, connected, receivedAt } = useSentinelSocket();
  const now = useNow();
  const online = connected && !!state?.system.mqtt_connected;
  const anomaly = state?.anomaly ?? null;
  const anomalyHistory = state?.anomaly_history ?? [];
  const telemetryHistory = state?.history ?? [];
  const fresh = online && isFresh(anomaly?.ts, now);
  const environmentAnalysis = useMemo(() => analyzeEnvironment({
    telemetryHistory, anomaly, anomalyHistory, deviceId: state?.telemetry?.device_id, online, now,
  }), [telemetryHistory, anomaly, anomalyHistory, state?.telemetry?.device_id, online, now]);

  const risk: { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' } =
    !online ? { label: 'OFFLINE', tone: 'neutral' }
      : !anomaly ? { label: 'WAITING', tone: 'neutral' }
        : !fresh ? { label: 'STALE DATA', tone: 'neutral' }
          : !anomaly.ready ? { label: 'CALIBRATING', tone: 'warning' }
            : anomaly.anomaly ? { label: 'ANOMALY DETECTED', tone: 'danger' }
              : { label: 'NORMAL', tone: 'success' };

  const interpretation = !online ? 'Waiting for a live MQTT connection.'
    : !anomaly ? 'Waiting for the anomaly model to report its first analysis.'
      : !fresh ? 'The last model result is stale; connect the sensor and AI services.'
        : !anomaly.ready ? 'The model is learning its baseline from incoming sensor readings.'
          : anomaly.anomaly ? 'The model classified this sensor combination as anomalous. Review the readings and site conditions.'
            : 'The model classified this sensor combination as consistent with its learned baseline.';

  const environmentalAlerts = useMemo(
    () => (state?.alerts ?? []).filter(alert => alert.type === 'ENVIRONMENTAL_ANOMALY').slice(0, 8),
    [state?.alerts],
  );

  return (
    <>
      <Header online={online} deviceId={state?.telemetry?.device_id} now={now} currentPage="environment" />
      <main className="dashboard-shell environment-dashboard">
        <div className="overview-heading flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="vision-eyebrow">SENTINEL-X / TIME SERIES ANALYSIS</p>
            <h1>AI Environment</h1>
          </div>
          <div className="vision-status-group">
            <StatusBadge tone={risk.tone} id="environment-dashboard-status">{risk.label}</StatusBadge>
            <span className="section-meta">{anomaly ? `Analysis ${formatTime(anomaly.ts)}` : 'Awaiting model output'}</span>
          </div>
        </div>

        <div className="environment-summary-grid">
          <section className={`panel environment-score-panel ${risk.tone === 'danger' && fresh ? 'is-anomaly' : ''}`}
            aria-labelledby="environment-score-title">
            <span className="environment-card-label" id="environment-score-title">
              <Gauge size={15} aria-hidden="true" />ANOMALY SCORE
            </span>
            <strong className="environment-score-value" id="environment-score">
              {fresh && anomaly?.ready && anomaly.score !== null ? formatNumber(anomaly.score, true) : '—'}
            </strong>
            <span className="environment-score-caption">
              {!anomaly?.ready ? 'Available after model calibration' : 'Raw Isolation Forest decision score'}
            </span>
          </section>
          <section className={`panel environment-risk-panel tone-${risk.tone}`} aria-labelledby="environment-risk-title">
            <span className="environment-card-label" id="environment-risk-title">
              <TriangleAlert size={15} aria-hidden="true" />MODEL CLASSIFICATION
            </span>
            <StatusBadge tone={risk.tone}>{risk.label}</StatusBadge>
            <p>
              {fresh && anomaly?.ready && anomaly.anomaly
                ? 'Sensor readings differ from the model baseline.'
                : fresh && anomaly?.ready ? 'No anomaly reported by the model.'
                  : 'No current classification available.'}
            </p>
          </section>
          <section className="panel environment-model-panel" aria-labelledby="environment-model-title">
            <span className="environment-card-label" id="environment-model-title">
              <BrainCircuit size={15} aria-hidden="true" />MODEL
            </span>
            <strong>{modelName(anomaly)}</strong>
            <span>{anomaly?.ready ? `${anomalyHistory.length} recent analyses` : 'Unsupervised baseline learning'}</span>
          </section>
        </div>

        {environmentIntelligenceEnabled() && <EnvironmentInterpretationPanel analysis={environmentAnalysis} />}

        <section aria-labelledby="environment-trends-title">
          <div className="section-heading">
            <h2 id="environment-trends-title"><Activity size={16} aria-hidden="true" />Sensor time series</h2>
            <span className="section-meta">{telemetryHistory.length} recent readings</span>
          </div>
          <div className="environment-trends-grid">
            {featureCharts.map(metric => <SensorTrendChart key={metric.key} telemetry={telemetryHistory} metric={metric} />)}
          </div>
        </section>

        <section aria-labelledby="score-history-title">
          <div className="section-heading">
            <h2 id="score-history-title"><ChartNoAxesCombined size={16} aria-hidden="true" />Model score over time</h2>
            <span className="section-meta">Actual Isolation Forest outputs · calibration samples excluded</span>
          </div>
          <AnomalyScoreChart results={anomalyHistory} live={fresh} />
        </section>

        <section className="panel environment-analysis-panel" aria-labelledby="current-analysis-title">
          <div className="panel-heading">
            <h2 id="current-analysis-title"><BrainCircuit size={17} className="text-cyan-400" aria-hidden="true" />Current analysis</h2>
            <StatusBadge tone={risk.tone}>{risk.label}</StatusBadge>
          </div>
          <p className="environment-interpretation">{interpretation}</p>
          <p className="environment-model-note">
            Isolation Forest classifies each temperature/humidity/gas sample against its learned baseline;
            the charts show those measurements over time. This model does not forecast future incidents.
          </p>
        </section>

        <section className="panel environment-history-panel" aria-labelledby="environment-history-title">
          <div className="panel-heading">
            <h2 id="environment-history-title"><Clock3 size={17} className="text-cyan-400" aria-hidden="true" />Anomaly events</h2>
            <span className="section-meta">Recent backend alerts</span>
          </div>
          {environmentalAlerts.length === 0 ? <div className="environment-events-empty">
            <Activity size={20} aria-hidden="true" />
            <span>No environmental anomaly events have been recorded.</span>
          </div> : <ul className="environment-event-list">
            {environmentalAlerts.map(alert => <li key={alert.id}>
              <span className="environment-event-indicator"><TriangleAlert size={16} aria-hidden="true" /></span>
              <span><strong>{alert.message}</strong><small>Isolation Forest · {alert.severity.toUpperCase()}</small></span>
              <time dateTime={alert.ts}>{formatTime(alert.ts)}</time>
            </li>)}
          </ul>}
        </section>

        <footer className="dashboard-footer flex flex-wrap items-center justify-between gap-3">
          <span><span className={`tiny-dot ${fresh ? 'bg-emerald-400' : 'bg-slate-500'}`} />
            {fresh ? 'AI ENVIRONMENT ACTIVE' : 'WAITING FOR AI ENVIRONMENT'}</span>
          <span>Last received {formatTime(receivedAt)}<span className="footer-divider">/</span>SENTINEL-X</span>
        </footer>
      </main>
    </>
  );
}
