import { Camera, Cpu, Network, Server, RefreshCw } from 'lucide-react';

import type { SentinelState } from '../types/sentinel';
import { formatTime } from '../utils/format';
import { isFresh } from '../utils/status';

export default function SystemStatus({ state, connected, now }: {
  state: SentinelState | null; connected: boolean; now: number;
}) {
  const mqtt = connected && !!state?.system.mqtt_connected;
  const visionFresh = mqtt && isFresh(state?.vision?.ts, now);
  const anomalyFresh = mqtt && isFresh(state?.anomaly?.ts, now);
  const statuses = [
    { label: 'BACKEND', icon: Server, id: 'backend-status', value: connected ? 'ONLINE' : 'CONNECTING',
      tone: connected ? 'success' : 'warning' },
    { label: 'MQTT BROKER', icon: Network, id: 'mqtt-status', value: !connected ? 'UNKNOWN' : mqtt ? 'CONNECTED' : 'OFFLINE',
      tone: mqtt ? 'success' : 'neutral' },
    { label: 'AI VISION', icon: Camera, id: 'vision-status',
      value: !state?.vision ? 'WAITING' : !mqtt ? 'OFFLINE' : visionFresh ? 'ONLINE' : 'STALE',
      tone: visionFresh ? 'success' : 'neutral' },
    { label: 'AI ENVIRONMENT', icon: Cpu, id: 'anomaly-status',
      value: !state?.anomaly ? 'WAITING' : !mqtt ? 'OFFLINE' : !anomalyFresh ? 'STALE'
        : state.anomaly.ready ? 'ONLINE' : 'CALIBRATING',
      tone: anomalyFresh ? state?.anomaly?.ready ? 'success' : 'warning' : 'neutral' },
  ] as const;

  return (
    <section className="system-strip grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5" aria-label="System status">
      {statuses.map(({ label, icon: Icon, id, value, tone }) => (
        <div key={label} className="system-item">
          <span className="system-label"><Icon size={14} aria-hidden="true" />{label}</span>
          <span id={id} className={`system-value tone-${tone}`}><span className="status-dot" />{value}</span>
        </div>
      ))}
      <div className="system-item">
        <span className="system-label"><RefreshCw size={14} aria-hidden="true" />LAST UPDATE</span>
        <span className="system-value tabular-nums">{formatTime(state?.system.last_update)}</span>
      </div>
    </section>
  );
}
