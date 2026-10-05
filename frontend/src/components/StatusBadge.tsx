import type { ReactNode } from 'react';
import type { Tone } from '../utils/status';

export default function StatusBadge({ children, tone = 'neutral', id }: {
  children: ReactNode; tone?: Tone; id?: string;
}) {
  return <span id={id} className={`status-badge tone-${tone}`}><span className="status-dot" />{children}</span>;
}
