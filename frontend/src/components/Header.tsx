import { Clock3, ShieldCheck } from 'lucide-react';

import { formatTime } from '../utils/format';
import StatusBadge from './StatusBadge';

export default function Header({ online, deviceId, now }: { online: boolean; deviceId?: string; now: number }) {
  return (
    <header className="app-header">
      <div className="header-inner flex flex-wrap items-center justify-between gap-4">
        <a href="#overview" className="brand flex items-center gap-3" aria-label="Sentinel-X overview">
          <span className="brand-icon"><ShieldCheck size={25} strokeWidth={1.7} aria-hidden="true" /></span>
          <span><span className="brand-name">SENTINEL<span className="text-cyan-400">-X</span></span>
            <span className="brand-subtitle">Industrial Security Node</span></span>
        </a>
        <div className="flex flex-wrap items-center gap-4 sm:gap-6">
          <span className="header-device">{deviceId || 'AWAITING NODE'}</span>
          <StatusBadge id="system-online" tone={online ? 'success' : 'neutral'}>
            SYSTEM {online ? 'ONLINE' : 'OFFLINE'}
          </StatusBadge>
          <span className="header-clock hidden sm:flex"><Clock3 size={14} aria-hidden="true" />{formatTime(now)}</span>
        </div>
      </div>
    </header>
  );
}
