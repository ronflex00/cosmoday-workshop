import { useMemo } from 'react';
import { ChartNoAxesCombined } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import type { SensorTelemetry } from '../types/sentinel';
import { formatNumber, formatTime } from '../utils/format';

const metrics = [
  { key: 'temperature', title: 'Temperature', unit: '°C', color: '#22d3ee' },
  { key: 'humidity', title: 'Humidity', unit: '%', color: '#818cf8' },
  { key: 'gas', title: 'Gas', unit: 'raw', color: '#fbbf24' },
] as const;

export default function SensorChart({ history, live }: { history: SensorTelemetry[]; live: boolean }) {
  const points = useMemo(() => history.slice(-120), [history]);
  return (
    <section aria-labelledby="chart-title" id="analytics">
      <div className="section-heading"><h2 id="chart-title"><ChartNoAxesCombined size={16} aria-hidden="true" />Environmental trends</h2>
        <span className="section-meta">{points.length} recent readings{!live && points.length > 0 ? ' · last known data' : ''}</span></div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {metrics.map(metric => (
          <article key={metric.key} className={`panel chart-card ${!live ? 'data-muted' : ''}`} aria-label={`${metric.title} chart`}>
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
                    : <div className="chart-tooltip"><span>{formatTime(String(label))}</span><strong style={{ color: metric.color }}>{formatNumber(payload[0].value, true)} {metric.unit}</strong></div>} />
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
