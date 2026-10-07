import { isCommandResult, isSentinelState, isTelemetryTrend } from '../types/sentinel';
import type { Command, CommandResult, SentinelState, TelemetryTrend } from '../types/sentinel';

export const API_URL = (import.meta.env.VITE_API_URL || (import.meta.env.PROD ? window.location.origin : 'http://localhost:8000')).replace(/\/+$/, '');
export const WS_URL = import.meta.env.VITE_WS_URL || `${API_URL.replace(/^http/, 'ws')}/ws`;

export async function fetchTrends(signal: AbortSignal): Promise<TelemetryTrend[]> {
  const response = await fetch(`${API_URL}/api/v1/history/telemetry_trends?limit=120`, { signal, cache: 'no-store' });
  if (!response.ok) throw new Error('Trend history unavailable');
  const data: unknown = await response.json();
  if (!data || typeof data !== 'object' || !('items' in data) || !Array.isArray(data.items)) throw new Error('Invalid trend history');
  const samples: TelemetryTrend[] = [];
  for (const item of data.items) {
    if (!item || typeof item !== 'object' || !isTelemetryTrend(item.data)) throw new Error('Invalid trend summary');
    samples.push(item.data);
  }
  return samples.reverse();
}

export async function fetchState(signal: AbortSignal): Promise<SentinelState> {
  const response = await fetch(`${API_URL}/api/v1/state`, { signal, cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`State request failed (${response.status})`);
  }
  const data: unknown = await response.json();
  if (!isSentinelState(data)) {
    throw new Error('Invalid Sentinel-X state');
  }
  return data;
}

export async function sendCommand(command: Command, signal: AbortSignal): Promise<CommandResult> {
  const response = await fetch(`${API_URL}/api/v1/commands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(command),
    signal,
  });
  if (response.status === 503) {
    throw new Error('MQTT is unavailable. Command publication was not confirmed.');
  }
  if (!response.ok) {
    throw new Error('Command publication was not confirmed. Check the node before retrying.');
  }
  const result: unknown = await response.json();
  if (!isCommandResult(result) || result.command.buzzer !== command.buzzer || result.command.led !== command.led) {
    throw new Error('The backend returned an invalid command confirmation.');
  }
  return result;
}
