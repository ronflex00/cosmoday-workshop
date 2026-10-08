import type { AnomalyResult, SensorTelemetry } from '../types/sentinel';
import type { Tone } from './status';

export const ENVIRONMENT_FRESH_MS = 30_000;
export const ENVIRONMENT_FUTURE_TOLERANCE_MS = 5_000;

export type EnvironmentRisk = 'NORMAL' | 'WATCH' | 'WARNING' | 'CRITICAL';
export type EnvironmentAvailability = 'ready' | 'offline' | 'waiting' | 'calibrating' | 'stale' | 'insufficient';
export type TrendStrength = 'stable' | 'weak' | 'moderate' | 'strong';
export type EnvironmentFeature = 'temperature' | 'humidity' | 'gas';

export interface FeatureTrend {
  feature: EnvironmentFeature;
  direction: 'up' | 'down' | 'stable';
  strength: TrendStrength;
  absoluteChange: number | null;
  relativeChange: number | null;
  observation: string;
}

export interface EnvironmentInterpretation {
  availability: EnvironmentAvailability;
  risk: EnvironmentRisk | null;
  label: string;
  tone: Tone;
  title: string;
  observations: string[];
  recommendedAction: string;
  trends: FeatureTrend[];
  sampleCount: number;
  anomalousSamples: number;
  modelNote: string;
}

export interface EnvironmentAnalysisInput {
  telemetryHistory?: readonly SensorTelemetry[];
  anomaly?: AnomalyResult | null;
  anomalyHistory?: readonly AnomalyResult[];
  deviceId?: string;
  online: boolean;
  now: number;
}

const modelNote = 'Trends describe measurements alongside the Isolation Forest result; they do not identify the cause of an anomaly. A normal model result is not a safety guarantee.';
const metrics: { key: EnvironmentFeature; name: string; unit: string; stable: number; weak: number; moderate: number }[] = [
  { key: 'temperature', name: 'Temperature', unit: '°C', stable: 0.2, weak: 1, moderate: 3 },
  { key: 'humidity', name: 'Humidity', unit: 'percentage points', stable: 1, weak: 5, moderate: 15 },
  { key: 'gas', name: 'Gas level', unit: 'raw units', stable: 5, weak: 25, moderate: 100 },
];

function timestamp(value: string): number | null {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function fresh(value: string, now: number): boolean {
  const time = timestamp(value);
  return time !== null && now - time <= ENVIRONMENT_FRESH_MS
    && now - time >= -ENVIRONMENT_FUTURE_TOLERANCE_MS;
}

function signed(value: number, decimals = 1): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(decimals)}`;
}

export function interpretFeatureTrend(
  feature: EnvironmentFeature, baseline: number, latest: number,
): FeatureTrend {
  const metric = metrics.find(candidate => candidate.key === feature)!;
  const rawChange = latest - baseline;
  const absoluteChange = Number.isFinite(rawChange) ? rawChange : null;
  const magnitude = Math.abs(rawChange);
  const tinyReference = Math.abs(baseline) < 1e-6;
  // Divide before subtracting so opposite large finite values do not overflow a valid percentage.
  const rawRelative = tinyReference ? null : (latest / Math.abs(baseline) - Math.sign(baseline)) * 100;
  const relativeChange = rawRelative !== null && Number.isFinite(rawRelative) && Math.abs(rawRelative) <= 1_000_000
    ? rawRelative : null;
  const relativeMagnitude = relativeChange === null ? null : Math.abs(relativeChange);
  // These bands qualify observations, never replace the model's classification.
  const strength: TrendStrength = magnitude <= metric.stable ? 'stable'
    : feature === 'gas' && relativeMagnitude !== null
      ? relativeMagnitude < 10 && magnitude < metric.weak ? 'weak'
        : relativeMagnitude < 50 && magnitude < metric.moderate ? 'moderate' : 'strong'
      : magnitude < metric.weak ? 'weak' : magnitude < metric.moderate ? 'moderate' : 'strong';
  const direction = strength === 'stable' ? 'stable' : latest > baseline ? 'up' : 'down';
  const relativeDescription = baseline === 0 ? 'relative change unavailable from a zero baseline'
    : tinyReference ? 'relative change unavailable from a near-zero baseline'
      : 'relative change unavailable at this numeric scale';
  const variation = `${absoluteChange === null ? 'absolute change exceeds numeric range' : `${signed(absoluteChange)} ${metric.unit}`}; ${relativeChange === null
    ? relativeDescription : `${signed(relativeChange)}% relative change`}`;
  const observation = strength === 'stable' ? `${metric.name} remains stable (${variation}).`
    : `${metric.name} ${direction === 'up' ? 'rising' : 'falling'} ${strength === 'weak'
      ? 'slightly' : strength === 'moderate' ? 'moderately' : 'strongly'} (${variation}).`;
  return { feature, direction, strength, absoluteChange, relativeChange, observation };
}

function fallback(availability: Exclude<EnvironmentAvailability, 'ready'>): EnvironmentInterpretation {
  const details = {
    offline: ['MQTT OFFLINE', 'Live analysis unavailable', 'Reconnect the backend and MQTT broker.'],
    waiting: ['WAITING FOR MODEL', 'No model result available', 'Start the sensor and Isolation Forest service.'],
    calibrating: ['MODEL CALIBRATING', 'Learning the environmental baseline', 'Allow baseline learning to finish before interpreting model risk.'],
    stale: ['STALE RESULT', 'No current Isolation Forest result', 'Check the sensor, model service and device clocks.'],
    insufficient: ['INSUFFICIENT DATA', 'Waiting for comparable readings', 'Collect at least two fresh readings from the same sensor node.'],
  }[availability];
  return {
    availability, risk: null, label: details[0], tone: availability === 'calibrating' ? 'warning' : 'neutral',
    title: details[1], observations: ['No current environmental safety conclusion is available.'],
    recommendedAction: details[2], trends: [], sampleCount: 0, anomalousSamples: 0, modelNote,
  };
}

function currentTelemetry(input: EnvironmentAnalysisInput): SensorTelemetry[] {
  const history = input.telemetryHistory ?? [];
  const device = input.deviceId ?? history.at(-1)?.device_id;
  const points: SensorTelemetry[] = [];
  let lastTime = Number.NEGATIVE_INFINITY;
  for (const point of history) {
    const time = timestamp(point.ts);
    if (point.device_id !== device || time === null || time <= lastTime || !fresh(point.ts, input.now)
      || !metrics.every(metric => Number.isFinite(point[metric.key]))) continue;
    lastTime = time;
    points.push(point);
  }
  return points.slice(-6);
}

function interpretRecentTrend(feature: EnvironmentFeature, points: SensorTelemetry[]): FeatureTrend {
  const net = interpretFeatureTrend(feature, points[0][feature], points[points.length - 1][feature]);
  const minimum = Math.min(...points.map(point => point[feature]));
  const maximum = Math.max(...points.map(point => point[feature]));
  const variation = interpretFeatureTrend(feature, minimum, maximum);
  // A return to the first value does not make a fluctuating measurement stable.
  if (net.strength === 'stable' && variation.strength !== 'stable') {
    const metric = metrics.find(candidate => candidate.key === feature)!;
    return {
      ...net, strength: variation.strength,
      observation: `${metric.name} varied ${variation.strength === 'weak' ? 'slightly' : variation.strength === 'moderate'
        ? 'moderately' : 'strongly'} (${variation.absoluteChange === null ? 'range exceeds numeric limits' : `range ${variation.absoluteChange.toFixed(1)} ${metric.unit}`}; net change ${net.absoluteChange === null ? 'unavailable' : `${signed(net.absoluteChange)} ${metric.unit}`}).`,
    };
  }
  return net;
}

function persistence(input: EnvironmentAnalysisInput) {
  let episode = false;
  let normalStreak = 0;
  let lastTime: number | null = null;
  let window: AnomalyResult[] = [];
  // Replay received order: duplicate and backwards timestamps never become extra evidence.
  // The cached history can recover an episode; its absence cannot prove an older episode ended.
  for (const point of [...(input.anomalyHistory ?? []), ...(input.anomaly ? [input.anomaly] : [])]) {
    const time = timestamp(point.ts);
    if (time === null || time > input.now + ENVIRONMENT_FUTURE_TOLERANCE_MS
      || (lastTime !== null && time <= lastTime)) continue;
    if (lastTime !== null && time - lastTime > ENVIRONMENT_FRESH_MS) {
      window = [];
      normalStreak = 0;
    }
    lastTime = time;
    if (!point.ready || point.model !== 'isolation_forest' || !Number.isFinite(point.score)) {
      window = [];
      normalStreak = 0;
      continue;
    }
    window = [...window, point].slice(-3);
    normalStreak = point.anomaly ? 0 : normalStreak + 1;
    if (episode && normalStreak >= 2) {
      episode = false;
      window = [point];
    } else if (window.filter(result => result.anomaly).length >= 2) episode = true;
  }
  return { episode, window, normalStreak };
}

export function analyzeEnvironment(input: EnvironmentAnalysisInput): EnvironmentInterpretation {
  if (!input.online) return fallback('offline');
  const result = input.anomaly;
  if (!result) return fallback('waiting');
  if (!fresh(result.ts, input.now)) return fallback('stale');
  if (!result.ready) return fallback('calibrating');
  if (result.model !== 'isolation_forest' || !Number.isFinite(result.score)) return fallback('waiting');

  const points = currentTelemetry(input);
  const trends = points.length < 2 ? [] : metrics.map(metric => interpretRecentTrend(metric.key, points));
  const { episode, window, normalStreak } = persistence(input);
  const anomalousSamples = window.filter(point => point.anomaly).length;
  const latestAcceptedAnomaly = window.at(-1)?.anomaly ?? result.anomaly;
  if (!episode && !latestAcceptedAnomaly && (trends.length === 0 || normalStreak < 2)) return fallback('insufficient');
  const unusualTrend = trends.some(trend => trend.strength === 'moderate' || trend.strength === 'strong');
  const risk: EnvironmentRisk = episode ? 'CRITICAL' : latestAcceptedAnomaly ? 'WARNING' : unusualTrend ? 'WATCH' : 'NORMAL';
  const messages = {
    NORMAL: ['Model currently reports normal', 'Continue monitoring; no anomaly is reported for the current sample.'],
    WATCH: ['Measurements changing while the model reports normal', 'Review the trends and continue monitoring for model anomalies.'],
    WARNING: ['Isolated environmental anomaly', 'Check the recent readings and inspect the monitored area.'],
    CRITICAL: ['Persistent environmental anomaly', 'Inspect the monitored area immediately.'],
  }[risk];
  const observations = trends.length ? trends.map(trend => trend.observation)
    : ['Not enough fresh readings from the same node to describe sensor trends.'];
  observations.push(`${anomalousSamples} anomalous ${anomalousSamples === 1 ? 'sample' : 'samples'} among the last ${window.length} distinct model ${window.length === 1 ? 'result' : 'results'}.`);
  if (episode) observations.push(normalStreak > 0
    ? 'One normal model result observed; waiting for a second consecutive normal result to clear the episode.'
    : 'Critical episode remains active until two consecutive fresh normal model results.');
  return {
    availability: 'ready', risk, label: risk, tone: risk === 'CRITICAL' ? 'danger'
      : risk === 'WARNING' || risk === 'WATCH' ? 'warning' : 'success',
    title: messages[0], observations, recommendedAction: messages[1], trends,
    sampleCount: points.length, anomalousSamples, modelNote,
  };
}

export function environmentIntelligenceEnabled(): boolean {
  return import.meta.env.VITE_ENVIRONMENT_INTELLIGENCE !== 'false';
}
