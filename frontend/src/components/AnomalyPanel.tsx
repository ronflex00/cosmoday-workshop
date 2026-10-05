import { Activity, Cpu, ShieldCheck, TriangleAlert } from 'lucide-react';

import type { AnomalyResult } from '../types/sentinel';
import { formatNumber, formatTime } from '../utils/format';
import StatusBadge from './StatusBadge';

export default function AnomalyPanel({ anomaly, fresh, online }: {
  anomaly: AnomalyResult | null; fresh: boolean; online: boolean;
}) {
  const calibrating = anomaly?.ready === false;
  const flagged = anomaly?.ready === true && anomaly.anomaly;
  const label = !anomaly ? 'AWAITING DATA' : calibrating ? 'CALIBRATING' : flagged ? 'ANOMALY' : 'NORMAL';
  const tone = !anomaly ? 'neutral' : flagged ? 'danger' : calibrating ? 'warning' : 'success';
  const Icon = !anomaly || calibrating ? Activity : flagged ? TriangleAlert : ShieldCheck;

  return (
    <section className={`panel ai-panel accent-${fresh ? tone : 'neutral'}`} aria-labelledby="anomaly-title">
      <div className="panel-heading"><h2 id="anomaly-title"><Cpu size={17} className="text-cyan-400" aria-hidden="true" />AI Environment</h2>
        <StatusBadge tone={fresh ? 'info' : 'neutral'}>{!anomaly ? 'WAITING' : !online ? 'OFFLINE' : fresh ? 'LIVE' : 'STALE'}</StatusBadge></div>
      <div className="ai-content">
        <div className={`detection-summary ${!fresh ? 'data-muted' : ''}`}>
          <span className={`detection-icon tone-${tone}`}><Icon size={30} strokeWidth={1.5} aria-hidden="true" /></span>
          <div><p id="anomaly-result" className={`detection-title tone-${tone}`}>{label}</p>
            <p className="muted text-xs mt-1">{!anomaly ? 'Waiting for environmental analysis' : !fresh ? 'Last known analysis · awaiting updates'
              : calibrating ? 'Learning the normal environment' : flagged ? 'Readings differ from the learned baseline' : 'Readings match the learned baseline'}</p></div>
        </div>
        <div className="anomaly-metrics flex items-end justify-between gap-4">
          <div><span className="metric-label">ANOMALY SCORE</span><p id="anomaly-score" className="metric-value tabular-nums">
            {anomaly?.score == null ? '—' : anomaly.score.toFixed(3)}</p></div>
          <span className="model-label">{!anomaly ? 'Model pending' : anomaly.model === 'isolation_forest' ? 'IsolationForest' : anomaly.model}</span>
        </div>
      </div>
      <div className="analyzed-readings grid grid-cols-3 gap-3">
        <span>TEMP <b>{formatNumber(anomaly?.features.temperature)}{anomaly ? '°' : ''}</b></span>
        <span>HUMIDITY <b>{formatNumber(anomaly?.features.humidity)}{anomaly ? '%' : ''}</b></span>
        <span>GAS <b>{formatNumber(anomaly?.features.gas, true)}</b></span>
      </div>
      <div className="panel-footnote"><span>{calibrating ? 'Score available after calibration' : 'Last environmental analysis'}</span><span>{formatTime(anomaly?.ts)}</span></div>
    </section>
  );
}
