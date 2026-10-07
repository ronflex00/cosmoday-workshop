export interface SensorFeatures {
  temperature: number;
  humidity: number;
  gas: number;
}

export interface SensorTelemetry extends SensorFeatures {
  device_id: string;
  ts: string;
  motion: boolean;
}

export interface VisionResult {
  ts: string;
  person_detected: boolean;
  confidence: number;
  source: string;
}

export interface DeviceStatus {
  device_id: string;
  online: boolean;
  ip: string | null;
  rssi: number | null;
}

export type AnomalyResult = {
  ts: string;
  model: string;
  features: SensorFeatures;
} & (
  | { ready: false; anomaly: false; score: null }
  | { ready: true; anomaly: boolean; score: number }
);

export interface Alert {
  id: string;
  ts: string;
  type: 'INTRUSION' | 'ENVIRONMENTAL_ANOMALY' | 'SYSTEM';
  severity: 'info' | 'warning' | 'critical';
  message: string;
}

export interface SentinelState {
  telemetry: SensorTelemetry | null;
  device?: DeviceStatus | null;
  vision: VisionResult | null;
  anomaly: AnomalyResult | null;
  system: { mqtt_connected: boolean; last_update: string | null };
  history: SensorTelemetry[];
  anomaly_history?: AnomalyResult[];
  alerts: Alert[];
}

export interface StateMessage {
  type: 'state';
  data: SentinelState;
}

export interface Command {
  buzzer: boolean;
  led: 'red' | 'green';
}

export interface CommandResult {
  status: 'published';
  topic: 'sentinel/commands';
  command: Command;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isTimestamp(value: unknown): value is string {
  return typeof value === 'string' && Number.isFinite(Date.parse(value));
}

function isFeatures(value: unknown): value is SensorFeatures {
  return isRecord(value) && isNumber(value.temperature) && isNumber(value.humidity)
    && value.humidity >= 0 && value.humidity <= 100 && isNumber(value.gas) && value.gas >= 0;
}

function isTelemetry(value: unknown): value is SensorTelemetry {
  return isRecord(value) && isFeatures(value) && typeof value.device_id === 'string'
    && value.device_id.trim().length > 0 && isTimestamp(value.ts) && typeof value.motion === 'boolean';
}

function isVision(value: unknown): value is VisionResult {
  return isRecord(value) && isTimestamp(value.ts) && typeof value.person_detected === 'boolean'
    && isNumber(value.confidence) && value.confidence >= 0 && value.confidence <= 1
    && typeof value.source === 'string' && value.source.length > 0;
}

function isDeviceStatus(value: unknown): value is DeviceStatus {
  return isRecord(value) && typeof value.device_id === 'string' && value.device_id.trim().length > 0
    && typeof value.online === 'boolean'
    && (value.ip === null || typeof value.ip === 'string')
    && (value.rssi === null || (isNumber(value.rssi) && Number.isInteger(value.rssi)
      && value.rssi >= -127 && value.rssi <= 0))
    && (!value.online || (typeof value.ip === 'string' && isNumber(value.rssi)));
}

function isAnomaly(value: unknown): value is AnomalyResult {
  return isRecord(value) && isTimestamp(value.ts) && typeof value.model === 'string'
    && value.model.length > 0 && isFeatures(value.features) && (
      (value.ready === false && value.anomaly === false && value.score === null)
      || (value.ready === true && typeof value.anomaly === 'boolean' && isNumber(value.score))
    );
}

function isAlert(value: unknown): value is Alert {
  return isRecord(value) && typeof value.id === 'string' && value.id.length > 0 && isTimestamp(value.ts)
    && (value.type === 'INTRUSION' || value.type === 'ENVIRONMENTAL_ANOMALY' || value.type === 'SYSTEM')
    && (value.severity === 'info' || value.severity === 'warning' || value.severity === 'critical')
    && typeof value.message === 'string' && value.message.trim().length > 0;
}

export function isSentinelState(value: unknown): value is SentinelState {
  return isRecord(value)
    && (value.telemetry === null || isTelemetry(value.telemetry))
    && (value.device === undefined || value.device === null || isDeviceStatus(value.device))
    && (value.vision === null || isVision(value.vision))
    && (value.anomaly === null || isAnomaly(value.anomaly))
    && isRecord(value.system) && typeof value.system.mqtt_connected === 'boolean'
    && (value.system.last_update === null || isTimestamp(value.system.last_update))
    && Array.isArray(value.history) && value.history.every(isTelemetry)
    && (value.anomaly_history === undefined
      || (Array.isArray(value.anomaly_history) && value.anomaly_history.every(isAnomaly)))
    && Array.isArray(value.alerts) && value.alerts.every(isAlert);
}

export function isStateMessage(value: unknown): value is StateMessage {
  return isRecord(value) && value.type === 'state' && isSentinelState(value.data);
}

export function isCommandResult(value: unknown): value is CommandResult {
  return isRecord(value) && value.status === 'published' && value.topic === 'sentinel/commands'
    && isRecord(value.command) && typeof value.command.buzzer === 'boolean'
    && (value.command.led === 'red' || value.command.led === 'green');
}
