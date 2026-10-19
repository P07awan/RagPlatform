import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { statusTone } from '../utils/status';
import { FlaskConical, Play } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { getPrerequisites, listDatasets, listEvaluations, runEvaluation } from '../api/evaluation';
import { EvaluationDetail } from '../components/evaluation/EvaluationDetail';
import { PageHeader } from '../components/layout/PageHeader';
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Spinner } from '../components/ui';
import { queryKeys } from '../hooks/useSystem';
import { formatDate, formatScore } from '../utils/format';

export function EvaluationsPage() {
  const { evaluationId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [dataset, setDataset] = useState<string>('');
  const [limit, setLimit] = useState<string>('');

  const runs = useQuery({
    queryKey: queryKeys.evaluations,
    queryFn: () => listEvaluations(50, 0),
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.status === 'queued' || r.status === 'running') ? 3000 : false),
  });
  const datasets = useQuery({ queryKey: queryKeys.datasets, queryFn: listDatasets });
  const prereq = useQuery({ queryKey: queryKeys.prerequisites, queryFn: getPrerequisites });

  const selectedDataset = dataset || datasets.data?.[0]?.name || '';
  const activeRun = runs.data?.items.some((r) => r.status === 'queued' || r.status === 'running') ?? false;
  const parsedLimit = limit ? Number.parseInt(limit, 10) : undefined;
  const limitInvalid = limit !== '' && (!Number.isFinite(parsedLimit) || (parsedLimit ?? 0) < 1);

  const start = useMutation({
    mutationFn: () => runEvaluation({ dataset: selectedDataset, limit: parsedLimit }),
    onSuccess: (run) => {
      void qc.invalidateQueries({ queryKey: queryKeys.evaluations });
      navigate(`/evaluations/${run.evaluation_id}`);
    },
  });

  const blockers = [
    ...(prereq.data?.missing ?? []),
    ...(activeRun ? ['Another evaluation is already running.'] : []),
    ...(!selectedDataset && datasets.isSuccess ? ['No evaluation datasets found on the server.'] : []),
  ];
  const canRun = prereq.isSuccess && blockers.length === 0 && !limitInvalid;

  return (
    <>
      <PageHeader title="Evaluations" description="Measure answer faithfulness, relevancy and retrieval quality with RAGAS." />

      <Card className="mb-6">
        <CardHeader title="Run evaluation" description="LLM-judged metrics call the OpenAI API and incur charges. Use a case limit for quick, cheap checks." />
        <div className="flex flex-col gap-4 p-5 md:flex-row md:items-end">
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-400">
            Dataset
            <select
              value={selectedDataset}
              onChange={(e) => setDataset(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
              disabled={!datasets.data?.length}
            >
              {datasets.data?.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.name} ({d.cases} cases)
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-400">
            Case limit (optional)
            <input
              type="number"
              min={1}
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              placeholder="all"
              className="w-32 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            />
          </label>
          <Button onClick={() => start.mutate()} disabled={!canRun} loading={start.isPending}>
            <Play className="h-4 w-4" aria-hidden /> Run evaluation
          </Button>
        </div>
        {prereq.data && (
          <p className="px-5 pb-2 text-xs text-slate-500">
            RAGAS {prereq.data.ragas_version ?? 'not installed'} · metrics: {prereq.data.available_metrics.join(', ') || 'none'}
          </p>
        )}
        {blockers.length > 0 && (
          <ul className="mx-5 mb-5 list-disc space-y-1 rounded-lg bg-amber-50 py-3 pr-3 pl-8 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200" aria-label="Evaluation prerequisites">
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        )}
        {prereq.isError && <ErrorState error={prereq.error} onRetry={() => prereq.refetch()} />}
        {start.isError && <ErrorState error={start.error} />}
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader title="History" />
          {runs.isLoading ? (
            <Spinner />
          ) : runs.isError ? (
            <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
          ) : !runs.data?.items.length ? (
            <EmptyState icon={<FlaskConical className="h-6 w-6" />} title="No evaluation runs yet" description="Run an evaluation to see real metric scores here." />
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {runs.data.items.map((r) => {
                const firstMetric = Object.entries(r.metrics)[0];
                return (
                  <li key={r.evaluation_id}>
                    <Link
                      to={`/evaluations/${r.evaluation_id}`}
                      className={`block px-5 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 ${r.evaluation_id === evaluationId ? 'bg-brand-50 dark:bg-brand-500/10' : ''}`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs">{r.evaluation_id.slice(0, 12)}</span>
                        <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        {r.dataset} · {r.total_cases} cases · {formatDate(r.created_at)}
                      </p>
                      {firstMetric && (
                        <p className="mt-1 text-xs text-slate-500">
                          {firstMetric[0]}: <span className="font-medium tabular-nums">{formatScore(firstMetric[1])}</span>
                        </p>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
        <div className="min-w-0">
          {evaluationId ? (
            <EvaluationDetail evaluationId={evaluationId} />
          ) : (
            <Card>
              <EmptyState title="Select an evaluation run" description="Choose a run from the history to inspect metrics and per-question results." />
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
