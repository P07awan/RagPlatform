import { useQuery } from '@tanstack/react-query';
import { statusTone } from '../../utils/status';
import { Download } from 'lucide-react';
import { useMemo, useState } from 'react';
import { getEvaluation, getEvaluationResults } from '../../api/evaluation';
import { queryKeys } from '../../hooks/useSystem';
import { downloadFile, formatDate, formatScore, metricLabel, toCsv } from '../../utils/format';
import { MetricsBarChart, ScoreDistributionChart } from '../charts/MetricsBarChart';
import { Badge, Button, Card, CardHeader, ErrorState, Spinner, StatCard } from '../ui';
import { ResultsTable } from './ResultsTable';

const ACTIVE = new Set(['queued', 'running']);

export function EvaluationDetail({ evaluationId }: { evaluationId: string }) {
  const [failedOnly, setFailedOnly] = useState(false);
  const [distMetric, setDistMetric] = useState<string | null>(null);

  const run = useQuery({
    queryKey: queryKeys.evaluation(evaluationId),
    queryFn: () => getEvaluation(evaluationId),
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? 3000 : false),
  });
  const results = useQuery({
    queryKey: [...queryKeys.evaluationResults(evaluationId), run.data?.completed_cases ?? 0, run.data?.status],
    queryFn: () => getEvaluationResults(evaluationId),
    enabled: !!run.data,
  });

  const items = useMemo(() => results.data?.items ?? [], [results.data]);
  const metricKeys = useMemo(() => {
    const keys = new Set<string>(Object.keys(run.data?.metrics ?? {}));
    for (const r of items) Object.keys(r.scores).forEach((k) => keys.add(k));
    return [...keys];
  }, [items, run.data]);
  const activeMetric = distMetric ?? metricKeys[0] ?? null;
  const distValues = useMemo(
    () => (activeMetric ? items.map((r) => r.scores[activeMetric]).filter((v): v is number => typeof v === 'number' && Number.isFinite(v)) : []),
    [items, activeMetric],
  );

  if (run.isLoading) return <Spinner label="Loading evaluation…" />;
  if (run.isError) return <ErrorState error={run.error} onRetry={() => run.refetch()} />;
  const r = run.data!;

  const exportJson = () => downloadFile(`evaluation-${r.evaluation_id}.json`, JSON.stringify({ run: r, results: items }, null, 2), 'application/json');
  const exportCsv = () =>
    downloadFile(
      `evaluation-${r.evaluation_id}.csv`,
      toCsv(
        items.map((it) => ({
          case_index: it.case_index,
          case_id: it.case_id,
          question: it.question,
          reference_answer: it.reference_answer,
          generated_answer: it.generated_answer,
          ...Object.fromEntries(metricKeys.map((k) => [k, it.scores[k] ?? ''])),
          latency_ms: it.latency_ms,
          error: it.error,
        })),
      ),
      'text/csv',
    );

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={<span className="font-mono">{r.evaluation_id}</span>}
          description={`${r.dataset} · created ${formatDate(r.created_at)}`}
          action={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={exportJson} disabled={items.length === 0}>
                <Download className="h-4 w-4" aria-hidden /> JSON
              </Button>
              <Button variant="secondary" onClick={exportCsv} disabled={items.length === 0}>
                <Download className="h-4 w-4" aria-hidden /> CSV
              </Button>
            </div>
          }
        />
        <div className="grid grid-cols-2 gap-4 p-5 md:grid-cols-4">
          <div>
            <p className="text-xs text-slate-500">Status</p>
            <Badge tone={statusTone(r.status)}>{r.status}</Badge>
          </div>
          <div>
            <p className="text-xs text-slate-500">Cases</p>
            <p className="font-medium tabular-nums">{r.total_cases}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Completed / failed</p>
            <p className="font-medium tabular-nums">
              {r.completed_cases} / <span className={r.failed_cases ? 'text-red-600' : undefined}>{r.failed_cases}</span>
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Duration</p>
            <p className="font-medium tabular-nums">{r.duration_seconds !== null ? `${r.duration_seconds.toFixed(1)} s` : '—'}</p>
          </div>
        </div>
        {r.error && <ErrorState error={new Error(r.error)} />}
        {ACTIVE.has(r.status) && (
          <div className="px-5 pb-5">
            <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
              <div className="h-full bg-brand-600 transition-all" style={{ width: `${r.total_cases ? ((r.completed_cases + r.failed_cases) / r.total_cases) * 100 : 0}%` }} />
            </div>
            <p className="mt-1 text-xs text-slate-500">Running… results refresh automatically.</p>
          </div>
        )}
      </Card>

      {Object.keys(r.metrics).length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {Object.entries(r.metrics).map(([k, v]) => (
              <StatCard key={k} label={metricLabel(k)} value={formatScore(v)} hint="mean over scored cases" />
            ))}
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader title="Aggregate scores" />
              <div className="p-4 text-slate-500">
                <MetricsBarChart metrics={r.metrics} />
              </div>
            </Card>
            <Card>
              <CardHeader
                title="Per-case distribution"
                action={
                  <select
                    aria-label="Metric for distribution"
                    value={activeMetric ?? ''}
                    onChange={(e) => setDistMetric(e.target.value)}
                    className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-900"
                  >
                    {metricKeys.map((k) => (
                      <option key={k} value={k}>{metricLabel(k)}</option>
                    ))}
                  </select>
                }
              />
              <div className="p-4 text-slate-500">
                <ScoreDistributionChart values={distValues} label={metricLabel(activeMetric ?? '')} />
              </div>
            </Card>
          </div>
        </>
      )}

      <Card>
        <CardHeader
          title="Per-question results"
          description={`${items.length} case${items.length === 1 ? '' : 's'} recorded`}
          action={
            <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
              <input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} /> Failed only
            </label>
          }
        />
        {results.isLoading ? <Spinner /> : results.isError ? <ErrorState error={results.error} onRetry={() => results.refetch()} /> : <ResultsTable items={items} metricKeys={metricKeys} showFailedOnly={failedOnly} />}
      </Card>
    </div>
  );
}
