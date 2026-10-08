import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import App from '../App';
import EnvironmentDashboard from './EnvironmentDashboard';
import EnvironmentInterpretationPanel from './EnvironmentInterpretationPanel';
import { analyzeEnvironment } from '../utils/environmentAnalysis';
import { isSentinelState, isStateMessage } from '../types/sentinel';
import type { SentinelState } from '../types/sentinel';

const fixtures = vi.hoisted(() => {
  const now = Date.parse('2026-10-07T14:00:00Z');
  const result = {
    ts: new Date(now).toISOString(), ready: true as const, anomaly: false, score: 0.1,
    model: 'isolation_forest', features: { temperature: 23, humidity: 45, gas: 150 },
  };
  const telemetry = {
    ...result.features, device_id: 'sentinel-01', ts: result.ts, motion: false,
  };
  const initialState = {
    telemetry, anomaly: result,
    vision: { ts: result.ts, person_detected: true, confidence: 0.95, source: 'webcam' },
    system: { mqtt_connected: true, last_update: result.ts },
    history: [{ ...telemetry, ts: new Date(now - 2_000).toISOString() }, telemetry],
    anomaly_history: [{ ...result, ts: new Date(now - 2_000).toISOString() }, result],
    alerts: [{ id: 'event-1', ts: result.ts, type: 'ENVIRONMENTAL_ANOMALY', severity: 'warning', message: 'Recorded environmental anomaly' }],
  };
  return { now, initialState, socket: { state: initialState as SentinelState | null,
    connected: true, error: null as string | null, receivedAt: result.ts } };
});

vi.mock('../hooks/useSentinelSocket', () => ({ useSentinelSocket: () => fixtures.socket }));
vi.mock('../hooks/useNow', () => ({ useNow: () => fixtures.now }));

beforeEach(() => {
  fixtures.socket.state = structuredClone(fixtures.initialState) as SentinelState;
  fixtures.socket.connected = true;
  vi.stubGlobal('window', { location: { pathname: '/', protocol: 'http:', hostname: 'localhost' } });
});
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe('existing dashboards and message contracts remain usable', () => {
  it('renders Overview with live telemetry, alerts and both manual controls', () => {
    const html = renderToStaticMarkup(<App />);
    for (const label of ['Security overview', 'temperature-value', 'humidity-value', 'gas-value',
      'ACTIVATE ALARM', 'STOP ALARM', 'Recorded environmental anomaly']) expect(html).toContain(label);
    expect(html).not.toContain('AI ENVIRONMENT INTERPRETATION');
  });
  it('renders AI Vision with its camera, confidence, model and existing event panel', async () => {
    const { default: VisionDashboard } = await import('./VisionDashboard');
    const html = renderToStaticMarkup(<VisionDashboard />);
    for (const label of ['AI Vision', 'Live webcam', '95%', 'CONFIDENCE', 'MODEL', 'Detection history']) expect(html).toContain(label);
    expect(html).not.toContain('AI ENVIRONMENT INTERPRETATION');
  });
  it('keeps every existing Environment panel beside the new interpretation', () => {
    const html = renderToStaticMarkup(<EnvironmentDashboard />);
    for (const label of ['ANOMALY SCORE', 'MODEL CLASSIFICATION', 'Isolation Forest', 'Sensor time series',
      'Model score over time', 'Current analysis', 'Anomaly events', 'Recorded environmental anomaly',
      'AI ENVIRONMENT INTERPRETATION', 'NORMAL']) expect(html).toContain(label);
  });
  it('disabling the additive layer leaves score, classification, charts and event panels working', () => {
    vi.stubEnv('VITE_ENVIRONMENT_INTELLIGENCE', 'false');
    const html = renderToStaticMarkup(<EnvironmentDashboard />);
    expect(html).not.toContain('AI ENVIRONMENT INTERPRETATION');
    for (const label of ['ANOMALY SCORE', 'MODEL CLASSIFICATION', 'Current analysis', 'Anomaly events', 'Sensor time series']) {
      expect(html).toContain(label);
    }
  });
  it('does not change the API or WebSocket state contract and accepts legacy optional fields', () => {
    const state = fixtures.socket.state!;
    const original = JSON.stringify(state);
    expect(isSentinelState(state)).toBe(true);
    expect(isStateMessage({ type: 'state', data: state })).toBe(true);
    const { anomaly_history: omittedHistory, ...legacy } = state;
    expect(omittedHistory).toBeDefined();
    expect(isSentinelState(legacy)).toBe(true);
    analyzeEnvironment({ telemetryHistory: state.history, anomaly: state.anomaly,
      anomalyHistory: state.anomaly_history, online: true, now: fixtures.now });
    expect(JSON.stringify(state)).toBe(original);
  });
  it('renders absent state without throwing or reporting NORMAL', () => {
    fixtures.socket.state = null;
    fixtures.socket.connected = false;
    const html = renderToStaticMarkup(<EnvironmentDashboard />);
    expect(html).toContain('MQTT OFFLINE');
    expect(html).toContain('No current environmental safety conclusion');
    expect(html).not.toContain('data-risk="NORMAL"');
    expect(renderToStaticMarkup(<App />)).toContain('Security overview');
  });
});

describe('new interpretation panel', () => {
  it.each(['NORMAL', 'WATCH', 'WARNING', 'CRITICAL'] as const)('renders %s with observations and action', risk => {
    const analysis = analyzeEnvironment({
      online: true, now: fixtures.now, anomaly: fixtures.initialState.anomaly,
      telemetryHistory: fixtures.initialState.history, anomalyHistory: fixtures.initialState.anomaly_history,
    });
    const html = renderToStaticMarkup(<EnvironmentInterpretationPanel analysis={{ ...analysis, risk, label: risk }} />);
    expect(html).toContain(`data-risk="${risk}"`);
    expect(html).toContain('Observations');
    expect(html).toContain('Recommended action');
  });
  it.each(['offline', 'waiting', 'calibrating', 'stale', 'insufficient'] as const)('renders the %s fallback without actions', availability => {
    const overrides = {
      offline: { online: false }, waiting: { anomaly: null },
      calibrating: { anomaly: { ...fixtures.initialState.anomaly, ready: false, anomaly: false, score: null } as const },
      stale: { now: fixtures.now + 31_000 }, insufficient: { telemetryHistory: [] },
    }[availability];
    const analysis = analyzeEnvironment({ online: true, now: fixtures.now,
      anomaly: fixtures.initialState.anomaly, telemetryHistory: fixtures.initialState.history, ...overrides });
    const html = renderToStaticMarkup(<EnvironmentInterpretationPanel analysis={analysis} />);
    expect(html).toContain(`data-risk="${availability}"`);
    expect(html).toContain('No current environmental safety conclusion');
    expect(html).not.toContain('<button');
  });
  it('performing interpretation never sends a browser command', () => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const state = fixtures.socket.state!;
    state.anomaly = { ...state.anomaly!, ready: true, score: -0.18, anomaly: true };
    state.anomaly_history = [
      { ...state.anomaly, ts: new Date(fixtures.now - 2_000).toISOString() }, state.anomaly,
    ];
    expect(renderToStaticMarkup(<EnvironmentDashboard />)).toContain('data-risk="CRITICAL"');
    expect(fetch).not.toHaveBeenCalled();
  });
});
