import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { metricLabel } from '../../utils/format';

/** Aggregate RAGAS scores (0–1) for one run. Only metrics with real values are plotted. */
export function MetricsBarChart({ metrics }: { metrics: Record<string, number | null> }) {
  const data = Object.entries(metrics)
    .filter(([, v]) => v !== null && Number.isFinite(v))
    .map(([k, v]) => ({ metric: metricLabel(k), score: Number((v as number).toFixed(3)) }));
  if (data.length === 0) return null;
  return (
    <div className="h-64 w-full" role="img" aria-label="Aggregate metric scores chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: -16 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="currentColor" strokeOpacity={0.1} />
          <XAxis dataKey="metric" tick={{ fontSize: 11, fill: 'currentColor' }} tickLine={false} axisLine={false} />
          <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: 'currentColor' }} tickLine={false} axisLine={false} />
          <Tooltip cursor={{ fillOpacity: 0.06 }} contentStyle={{ fontSize: 12, borderRadius: 8 }} />
          <Bar dataKey="score" fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={56} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Per-case distribution of one metric across the run (histogram of 0.1-wide buckets). */
export function ScoreDistributionChart({ values, label }: { values: number[]; label: string }) {
  if (values.length === 0) return null;
  const buckets = Array.from({ length: 10 }, (_, i) => ({ range: `${(i / 10).toFixed(1)}`, count: 0 }));
  for (const v of values) buckets[Math.min(9, Math.max(0, Math.floor(v * 10)))].count++;
  return (
    <div className="h-48 w-full" role="img" aria-label={`${label} distribution`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={buckets} margin={{ top: 8, right: 8, bottom: 8, left: -24 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="currentColor" strokeOpacity={0.1} />
          <XAxis dataKey="range" tick={{ fontSize: 10, fill: 'currentColor' }} tickLine={false} axisLine={false} />
          <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: 'currentColor' }} tickLine={false} axisLine={false} />
          <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
          <Bar dataKey="count" fill="#0ea5e9" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
