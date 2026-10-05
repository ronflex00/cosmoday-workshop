import { Bell, Info, ShieldAlert, TriangleAlert } from 'lucide-react';

import type { Alert } from '../types/sentinel';
import { formatTime } from '../utils/format';
import StatusBadge from './StatusBadge';

const labels = { INTRUSION: 'INTRUSION', ENVIRONMENTAL_ANOMALY: 'ENVIRONMENTAL ANOMALY', SYSTEM: 'SYSTEM' };

export default function AlertsPanel({ alerts }: { alerts: Alert[] }) {
  return (
    <section className="panel alerts-panel" aria-labelledby="alerts-title" id="alerts">
      <div className="panel-heading"><h2 id="alerts-title"><Bell size={17} className="text-cyan-400" aria-hidden="true" />Alert activity</h2>
        <span className="section-meta">{alerts.length} recent events</span></div>
      {alerts.length === 0 ? <div className="alerts-empty"><Bell size={27} strokeWidth={1.3} aria-hidden="true" />
        <strong>No alerts recorded</strong><span>Detection events will appear here.</span></div>
        : <ul className="alert-list" role="log" aria-label="Recent alerts" aria-live="polite" aria-relevant="additions">
          {alerts.map(alert => {
            const tone = alert.severity === 'critical' ? 'danger' : alert.severity === 'warning' ? 'warning' : 'info';
            const Icon = alert.type === 'INTRUSION' ? ShieldAlert : alert.type === 'ENVIRONMENTAL_ANOMALY' ? TriangleAlert : Info;
            return <li key={alert.id} className="alert-row">
              <span className={`alert-icon tone-${tone}`}><Icon size={18} strokeWidth={1.6} aria-hidden="true" /></span>
              <div className="min-w-0 flex-1"><p className="alert-message">{alert.message}</p><p className="alert-type">{labels[alert.type]}</p></div>
              <div className="alert-meta"><StatusBadge tone={tone}>{alert.severity.toUpperCase()}</StatusBadge>
                <time dateTime={alert.ts}>{formatTime(alert.ts)}</time></div>
            </li>;
          })}
        </ul>}
    </section>
  );
}
