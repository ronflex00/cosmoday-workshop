import { describe, expect, it } from 'vitest';

import { analyzeEnvironment, interpretFeatureTrend } from './environmentAnalysis';
import type { EnvironmentAnalysisInput } from './environmentAnalysis';
import type { AnomalyResult, SensorTelemetry } from '../types/sentinel';

const now = Date.parse('2026-10-07T14:00:00Z');
const ts = (seconds: number) => new Date(now + seconds * 1_000).toISOString();
const model = (seconds: number, anomalous = false): AnomalyResult => ({
  ts: ts(seconds), ready: true, anomaly: anomalous, score: anomalous ? -0.18 : 0.1,
  model: 'isolation_forest', features: { temperature: 23, humidity: 45, gas: 150 },
});
const telemetry = (seconds: number, overrides: Partial<SensorTelemetry> = {}): SensorTelemetry => ({
  ts: ts(seconds), device_id: 'sentinel-01', temperature: 23, humidity: 45, gas: 150,
  motion: false, ...overrides,
});
function analysis(overrides: Partial<EnvironmentAnalysisInput> = {}) {
  return analyzeEnvironment({
    online: true, now, anomaly: model(0), anomalyHistory: [model(-2), model(0)],
    telemetryHistory: [telemetry(-2), telemetry(0)], ...overrides,
  });
}

describe('environment trend observations', () => {
  it('reports signed absolute and relative changes without claiming feature attribution', () => {
    const result = interpretFeatureTrend('gas', 100, 520);
    expect(result.strength).toBe('strong');
    expect(result.absoluteChange).toBe(420);
    expect(result.relativeChange).toBe(420);
    expect(result.observation).toContain('+420.0%');
    expect(analysis().modelNote).toContain('do not identify the cause');
  });
  it('handles a zero baseline without Infinity, NaN or invented percentages', () => {
    const result = interpretFeatureTrend('gas', 0, 600);
    expect(result.relativeChange).toBeNull();
    expect(result.strength).toBe('strong');
    expect(result.observation).toContain('zero baseline');
  });
  it('handles near-zero baselines without meaningless or infinite relative change', () => {
    const result = interpretFeatureTrend('gas', 1e-300, 600);
    expect(result.relativeChange).toBeNull();
    expect(result.observation).toContain('near-zero baseline');
    expect(result.observation).not.toMatch(/Infinity|NaN/);
  });
  it('handles finite inputs whose difference exceeds the numeric range', () => {
    const result = interpretFeatureTrend('temperature', -1e308, 1e308);
    expect(result.absoluteChange).toBeNull();
    expect(result.relativeChange).toBe(200);
    expect(result.observation).not.toMatch(/Infinity|NaN/);
  });
  it('handles a large finite gas ratio and a fluctuating numeric range without rendering Infinity', () => {
    const result = analysis({ telemetryHistory: [telemetry(-4, { gas: 1e308 }), telemetry(-2, { gas: 0 }), telemetry(0, { gas: 1e308 })] });
    expect(result.risk).toBe('WATCH');
    expect(result.observations.join(' ')).not.toMatch(/Infinity|NaN/);
    expect(interpretFeatureTrend('gas', 1, 1e308).relativeChange).toBeNull();
  });
  it.each([
    [23, 23.1, 'stable', 'stable'], [23, 23.5, 'weak', 'up'],
    [23, 25, 'moderate', 'up'], [23, 27, 'strong', 'up'], [23, 19, 'strong', 'down'],
  ] as const)('interprets temperature %s to %s as %s / %s', (baseline, latest, strength, direction) => {
    expect(interpretFeatureTrend('temperature', baseline, latest)).toMatchObject({ strength, direction });
  });
  it('reports humidity changes as percentage points separately from relative percent', () => {
    expect(interpretFeatureTrend('humidity', 40, 50).observation).toContain('+10.0 percentage points; +25.0%');
  });
});

describe('environment risk qualifies actual Isolation Forest outputs', () => {
  it('reports NORMAL for a normal model result and stable fresh telemetry', () => {
    expect(analysis()).toMatchObject({ risk: 'NORMAL', availability: 'ready', sampleCount: 2 });
  });
  it('reports WATCH for changing measurements while Isolation Forest remains normal', () => {
    const result = analysis({ telemetryHistory: [telemetry(-2), telemetry(0, { gas: 600 })] });
    expect(result.risk).toBe('WATCH');
    expect(result.title).toContain('model reports normal');
  });
  it('does not call oscillating measurements stable merely because their endpoints match', () => {
    const result = analysis({ telemetryHistory: [telemetry(-4), telemetry(-2, { gas: 600 }), telemetry(0)] });
    expect(result.risk).toBe('WATCH');
    expect(result.observations.join(' ')).toContain('Gas level varied strongly');
  });
  it('isolated model anomaly is WARNING even without telemetry history', () => {
    expect(analysis({ anomaly: model(0, true), anomalyHistory: [], telemetryHistory: [] }).risk).toBe('WARNING');
  });
  it('two anomalies among three distinct outputs become CRITICAL', () => {
    expect(analysis({ anomaly: model(0, true), anomalyHistory: [model(-4, true), model(-2), model(0, true)] })
      .risk).toBe('CRITICAL');
  });
  it('two consecutive anomalies can become CRITICAL without requiring three outputs', () => {
    expect(analysis({ anomaly: model(0, true), anomalyHistory: [model(-2, true), model(0, true)] }).risk).toBe('CRITICAL');
  });
  it('latest snapshot and duplicated history timestamps count only once', () => {
    expect(analysis({ anomaly: model(0, true), anomalyHistory: [model(0, true), model(0, true)] }))
      .toMatchObject({ risk: 'WARNING', anomalousSamples: 1 });
  });
  it('ignores backwards model timestamps instead of sorting them into persistence', () => {
    expect(analysis({ anomaly: model(0, true), anomalyHistory: [model(0, true), model(-1, true)] }).risk).toBe('WARNING');
  });
  it('does not classify a backwards anomalous latest snapshot over a newer accepted normal result', () => {
    expect(analysis({ anomaly: model(-1, true), anomalyHistory: [model(-2), model(0)] }).risk).toBe('NORMAL');
  });
  it('a gap over thirty seconds breaks the counting window before an episode begins', () => {
    expect(analysis({ anomaly: model(0, true), anomalyHistory: [model(-31, true), model(0, true)] }).risk).toBe('WARNING');
  });
  it('matches backend counting of the last three results when each adjacent gap is under thirty seconds', () => {
    expect(analysis({ anomaly: model(0, true), anomalyHistory: [model(-58, true), model(-29), model(0, true)] }).risk)
      .toBe('CRITICAL');
  });
  it('critical remains latched during further anomalies and the first normal result', () => {
    const history = [model(-6, true), model(-4, true), model(-2, true), model(0)];
    expect(analysis({ anomalyHistory: history }).risk).toBe('CRITICAL');
    expect(analysis({ anomalyHistory: history }).observations.join(' ')).toContain('second consecutive normal');
  });
  it('two consecutive fresh normals clear the critical episode', () => {
    expect(analysis({ anomalyHistory: [model(-6, true), model(-4, true), model(-2), model(0)] }).risk).toBe('NORMAL');
  });
  it('a new episode can become CRITICAL after rearming', () => {
    expect(analysis({ anomaly: model(0, true), anomalyHistory: [model(-10, true), model(-8, true),
      model(-6), model(-4), model(-2, true), model(0, true)] }).risk).toBe('CRITICAL');
  });
  it('a gap does not claim an already critical episode cleared itself', () => {
    expect(analysis({ anomaly: model(0, true), anomalyHistory: [model(-50, true), model(-48, true), model(0, true)] })
      .risk).toBe('CRITICAL');
  });
  it('calibration breaks persistence evidence but does not clear an existing episode', () => {
    const calibration: AnomalyResult = { ...model(-2), ready: false, anomaly: false, score: null };
    expect(analysis({ anomaly: model(0, true), anomalyHistory: [model(-4, true), calibration, model(0, true)] }).risk).toBe('WARNING');
    expect(analysis({ anomaly: model(0, true), anomalyHistory: [model(-6, true), model(-4, true), calibration, model(0, true)] })
      .risk).toBe('CRITICAL');
  });
});

describe('fallbacks and telemetry isolation', () => {
  it.each([
    [{ online: false }, 'offline'], [{ anomaly: null }, 'waiting'],
    [{ anomaly: model(-31) }, 'stale'], [{ anomaly: model(6) }, 'stale'],
    [{ telemetryHistory: [] }, 'insufficient'],
    [{ anomaly: { ...model(0), ready: false, anomaly: false, score: null } }, 'calibrating'],
    [{ anomaly: { ...model(0), model: 'other_model' } }, 'waiting'],
  ] as const)('has a safe fallback for %j', (overrides, availability) => {
    expect(analysis(overrides)).toMatchObject({ availability, risk: null });
  });
  it('does not turn stale or future history into a trend', () => {
    expect(analysis({ telemetryHistory: [telemetry(-31), telemetry(0)] }).availability).toBe('insufficient');
    expect(analysis({ telemetryHistory: [telemetry(0), telemetry(6)] }).availability).toBe('insufficient');
  });
  it('one retained normal result cannot prove a previous episode cleared', () => {
    expect(analysis({ anomalyHistory: [model(0)] }).availability).toBe('insufficient');
  });
  it('a normal result immediately after one retained anomaly does not claim NORMAL', () => {
    expect(analysis({ anomalyHistory: [model(-2, true), model(0)] }).availability).toBe('insufficient');
  });
  it('only qualifies the exact supported Isolation Forest model identifier', () => {
    expect(analysis({ anomaly: { ...model(0), model: 'ISOLATION_FOREST' } }).availability).toBe('waiting');
  });
  it('never combines readings from different sensor devices', () => {
    expect(analysis({ deviceId: 'sentinel-01', telemetryHistory: [telemetry(-2, { device_id: 'other', gas: 0 }), telemetry(0)] })
      .availability).toBe('insufficient');
  });
  it('ignores out of order and duplicate telemetry timestamps', () => {
    expect(analysis({ telemetryHistory: [telemetry(-2), telemetry(0), telemetry(-1, { gas: 900 }), telemetry(0, { gas: 800 })] }))
      .toMatchObject({ risk: 'NORMAL', sampleCount: 2 });
  });
  it('limits trend comparison to the latest six fresh measurements', () => {
    expect(analysis({ telemetryHistory: Array.from({ length: 10 }, (_, index) => telemetry(index - 9)) }).sampleCount).toBe(6);
  });
});
