import { Camera, Eye, ScanEye, ShieldAlert, ShieldCheck } from 'lucide-react';

import type { VisionResult } from '../types/sentinel';
import { formatTime } from '../utils/format';
import StatusBadge from './StatusBadge';

export default function VisionPanel({ vision, fresh, online }: {
  vision: VisionResult | null; fresh: boolean; online: boolean;
}) {
  const detected = vision?.person_detected;
  const tone = !vision ? 'neutral' : detected ? 'danger' : 'success';
  const confidence = vision ? Math.round(vision.confidence * 100) : null;
  const Icon = !vision ? ScanEye : detected ? ShieldAlert : ShieldCheck;

  return (
    <section className={`panel ai-panel accent-${fresh ? tone : 'neutral'}`} aria-labelledby="vision-title">
      <div className="panel-heading">
        <h2 id="vision-title"><Eye size={17} className="text-cyan-400" aria-hidden="true" />AI Vision</h2>
        <StatusBadge tone={fresh ? 'success' : 'neutral'}>{!vision ? 'WAITING' : !online ? 'OFFLINE' : fresh ? 'CAMERA ONLINE' : 'STALE'}</StatusBadge>
      </div>
      <div className="ai-content">
        <div className={`detection-summary ${!fresh ? 'data-muted' : ''}`}>
          <span className={`detection-icon tone-${tone}`}><Icon size={30} strokeWidth={1.5} aria-hidden="true" /></span>
          <div><p id="vision-result" className={`detection-title tone-${tone}`}>
            {!vision ? 'WAITING FOR DATA' : detected ? 'INTRUSION' : 'CLEAR'}
          </p><p className="muted text-xs mt-1">{!vision ? 'Waiting for the first detection' : !fresh ? 'Last known detection · awaiting updates'
            : detected ? 'Human presence in the monitored area' : 'No human presence detected'}</p></div>
        </div>
        <div className="grid grid-cols-2 gap-5">
          <div><span className="metric-label">PERSON DETECTED</span>
            <p className={`metric-value tone-${tone}`}>{!vision ? '—' : detected ? 'YES' : 'NO'}</p></div>
          <div><span className="metric-label">CONFIDENCE</span><p id="vision-confidence" className="metric-value">{confidence == null ? '—' : `${confidence}%`}</p></div>
        </div>
      </div>
      <div className="confidence-track" role="progressbar" aria-label="Detection confidence" aria-valuemin={0} aria-valuemax={100} aria-valuenow={confidence ?? undefined}>
        <span className={`confidence-fill ${detected ? 'bg-red-400' : 'bg-emerald-400'}`} style={{ width: `${confidence ?? 0}%` }} />
      </div>
      <div className="panel-footnote"><span><Camera size={13} aria-hidden="true" />{vision?.source || 'Camera pending'}</span>
        <span>{formatTime(vision?.ts)}</span></div>
    </section>
  );
}
