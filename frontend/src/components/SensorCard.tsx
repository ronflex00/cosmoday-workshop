import type { LucideIcon } from 'lucide-react';

export default function SensorCard({ title, value, unit, icon: Icon, detail, live, id, motion }: {
  title: string; value: string; unit?: string; icon: LucideIcon;
  detail: string; live: boolean; id: string; motion?: boolean;
}) {
  return (
    <article className={`panel sensor-card ${!live ? 'data-muted' : ''}`} aria-label={title}>
      <div className="flex items-center justify-between gap-3">
        <span className="sensor-title">{title}</span>
        <Icon size={19} className={motion ? 'text-amber-400' : 'text-cyan-400'} strokeWidth={1.6} aria-hidden="true" />
      </div>
      <div className={`sensor-reading ${value === 'UNKNOWN' ? 'sensor-unknown' : ''}`}><span id={id}>{value}</span>{value !== '—' && unit && <span className="sensor-unit">{unit}</span>}</div>
      <p className="sensor-detail"><span className={`tiny-dot ${live ? motion ? 'bg-amber-400' : 'bg-cyan-400' : 'bg-slate-500'}`} />{detail}</p>
    </article>
  );
}
