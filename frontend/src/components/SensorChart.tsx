import { useEffect, useMemo, useState } from 'react';
import { ChartNoAxesCombined } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import type { SensorTelemetry, TelemetryTrend } from '../types/sentinel';
import { fetchTrends } from '../services/api';
import { formatNumber, formatTime } from '../utils/format';

const metrics = [
  { key: 'temperature', title: 'Temperature', unit: '°C', color: '#22d3ee' },
  { key: 'humidity', title: 'Humidity', unit: '%', color: '#818cf8' },
  { key: 'gas', title: 'Gas', unit: 'raw', color: '#fbbf24' },
] as const;

export default function SensorChart({ history, live }: { history: SensorTelemetry[]; live: boolean }) {
  const [mode, setMode] = useState<'live' | 'trends'>('live');
  const [trends, setTrends] = useState<TelemetryTrend[]>([]);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (mode !== 'trends') return;
    let stopped = false;
    let controller: AbortController | null = null;
    async function load() {
      controller?.abort();
      const request = new AbortController();
      controller = request;
      const timeout = window.setTimeout(() => request.abort(), 5000);
      try {
        const data = await fetchTrends(request.signal);
        if (!stopped) { setTrends(data); setError(false); }
      } catch { if (!stopped) setError(true); }
      finally { window.clearTimeout(timeout); }
    }
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => { stopped = true; controller?.abort(); window.clearInterval(timer); };
  }, [mode]);
  const points = useMemo(() => mode === 'live' ? history.slice(-120) : trends, [history, trends, mode]);
  return (
    <section aria-labelledby="chart-title" id="analytics">
      <div className="section-heading"><h2 id="chart-title"><ChartNoAxesCombined size={16} aria-hidden="true" />Environmental trends</h2>
        <div className="flex items-center gap-3"><select aria-label="Période des courbes" value={mode} onChange={event => setMode(event.target.value as 'live' | 'trends')} className="bg-slate-900 text-slate-200 rounded px-2 py-1 text-sm">
          <option value="live">Direct · toutes les mesures</option><option value="trends">Historique · moyennes par minute</option>
        </select><span className="section-meta">{points.length} {mode === 'trends' ? 'minutes' : 'recent readings'}</span></div></div>
      {mode === 'trends' && <p className="section-meta mb-3">{error ? 'Historique indisponible. Nouvelle tentative automatique.' : 'Moyennes des minutes enregistrées ; minimum et maximum dans les infobulles. La minute en cours reste en direct.'}</p>}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {metrics.map(metric => (
          <article key={metric.key} className={`panel chart-card ${mode === 'live' && !live ? 'data-muted' : ''}`} aria-label={`${metric.title} chart`}>
            <div className="chart-heading"><h3><span className="tiny-dot" style={{ background: metric.color }} />{metric.title}</h3>
              <span className="chart-latest">{formatNumber(points.at(-1)?.[metric.key], metric.key === 'gas')}<small>{metric.unit}</small></span></div>
            {points.length === 0 ? <div className="chart-empty"><ChartNoAxesCombined size={22} strokeWidth={1.3} aria-hidden="true" />Awaiting sensor telemetry</div>
              : <div className="chart-plot"><ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <AreaChart data={points} margin={{ top: 12, right: 6, left: -16, bottom: 0 }} accessibilityLayer>
                  <defs><linearGradient id={`fill-${metric.key}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={metric.color} stopOpacity={0.19} /><stop offset="100%" stopColor={metric.color} stopOpacity={0.01} />
                  </linearGradient></defs>
                  <CartesianGrid vertical={false} stroke="#25334a" strokeDasharray="3 4" />
                  <XAxis dataKey="ts" tickFormatter={formatTime} tick={{ fill: '#9aacc5', fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={44} interval="preserveStartEnd" />
                  <YAxis domain={['auto', 'auto']} tickFormatter={value => formatNumber(Number(value))} tick={{ fill: '#9aacc5', fontSize: 11 }} tickLine={false} axisLine={false} width={50} />
                  <Tooltip content={({ active, payload, label }) => !active || typeof payload?.[0]?.value !== 'number' ? null
                    : <div className="chart-tooltip"><span>{formatTime(String(label))}</span><strong style={{ color: metric.color }}>{formatNumber(payload[0].value, true)} {metric.unit}</strong>
                      {mode === 'trends' && <span>Min {formatNumber(payload[0].payload.minimum[metric.key])} · Max {formatNumber(payload[0].payload.maximum[metric.key])} · {payload[0].payload.sample_count} mesures</span>}
                    </div>} />
                  <Area type="linear" dataKey={metric.key} stroke={metric.color} strokeWidth={2} fill={`url(#fill-${metric.key})`}
                    isAnimationActive={false} dot={points.length === 1 ? { r: 3, fill: metric.color } : false} activeDot={{ r: 4, stroke: '#0f1b2d', strokeWidth: 2 }} />
                </AreaChart>
              </ResponsiveContainer></div>}
          </article>
        ))}
      </div>
    </section>
  );
}
