import { Activity, AlertTriangle, Database, FileText, FlaskConical, MessageSquare } from 'lucide-react';
import { statusTone } from '../utils/status';
import { Link } from 'react-router';
import { PageHeader } from '../components/layout/PageHeader';
import { Badge, Card, CardHeader, EmptyState, ErrorState, Spinner, StatCard } from '../components/ui';
import { useConfig, useHealth, useStats } from '../hooks/useSystem';
import { formatDate, formatMs, formatScore, metricLabel } from '../utils/format';

export function DashboardPage() {
  const stats = useStats();
  const health = useHealth();
  const config = useConfig();

  const indexed = stats.data?.documents_by_status.indexed ?? 0;
  const lastEval = stats.data?.last_evaluation ?? null;

  return (
    <>
      <PageHeader title="Dashboard" description="Live status of your document index, chat activity and evaluations." />

      {config.data && config.data.warnings.length > 0 && (
        <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
          <p className="flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4" aria-hidden /> Configuration warnings
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-6">
            {config.data.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Indexed documents"
          icon={<FileText className="h-4 w-4" />}
          value={stats.isLoading ? '…' : stats.isError ? '—' : indexed}
          hint={stats.data ? `${stats.data.documents_total} total uploads` : undefined}
        />
        <StatCard
          label="Indexed chunks"
          icon={<Database className="h-4 w-4" />}
          value={stats.data?.chunks_indexed ?? '—'}
          hint={stats.data && stats.data.chunks_indexed === null ? 'Vector store unavailable' : 'Vectors in Qdrant'}
        />
        <StatCard
          label="Backend"
          icon={<Activity className="h-4 w-4" />}
          value={<Badge tone={health.isError ? 'red' : statusTone(health.data?.status ?? 'unknown')}>{health.isError ? 'unreachable' : (health.data?.status ?? '…')}</Badge>}
          hint={health.data ? `v${health.data.version} · ${health.data.environment}` : undefined}
        />
        <StatCard
          label="Qdrant"
          icon={<Database className="h-4 w-4" />}
          value={<Badge tone={statusTone(health.data?.components.qdrant?.status ?? 'unknown')}>{health.data?.components.qdrant?.status ?? (health.isError ? 'unknown' : '…')}</Badge>}
          hint={health.data?.components.qdrant?.detail ?? undefined}
        />
      </div>

      {stats.isError && <ErrorState error={stats.error} onRetry={() => stats.refetch()} />}

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-1">
          <CardHeader title="Recent ingestion" action={<Link to="/documents" className="text-xs font-medium text-brand-600 hover:underline">View all</Link>} />
          {stats.isLoading ? (
            <Spinner />
          ) : !stats.data?.recent_documents.length ? (
            <EmptyState title="No documents yet" description="Upload PDF, TXT or Markdown files to build your index." action={<Link className="text-sm font-medium text-brand-600 hover:underline" to="/documents">Upload documents</Link>} />
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {stats.data.recent_documents.map((d) => (
                <li key={d.document_id} className="flex items-center justify-between gap-3 px-5 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{d.filename}</p>
                    <p className="text-xs text-slate-500">{formatDate(d.created_at)}</p>
                  </div>
                  <Badge tone={statusTone(d.status)}>{d.status}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="xl:col-span-1">
          <CardHeader title="Recent chats" action={<Link to="/chat" className="text-xs font-medium text-brand-600 hover:underline">Open chat</Link>} />
          {stats.isLoading ? (
            <Spinner />
          ) : !stats.data?.recent_chats.length ? (
            <EmptyState icon={<MessageSquare className="h-6 w-6" />} title="No chat activity yet" description="Questions you ask will appear here with latency and citation counts." />
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {stats.data.recent_chats.map((c) => (
                <li key={c.id} className="px-5 py-3">
                  <p className="truncate text-sm">{c.question_preview ?? '—'}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span>{formatDate(c.created_at)}</span>
                    <span>· {formatMs(c.latency_ms)}</span>
                    <span>· {c.citation_count ?? 0} citations</span>
                    {c.cache_hit && <Badge tone="blue">cache</Badge>}
                    {c.insufficient_context && <Badge tone="yellow">insufficient context</Badge>}
                    {c.status && c.status !== 'ok' && <Badge tone="red">{c.status}</Badge>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="xl:col-span-1">
          <CardHeader title="Last evaluation" action={<Link to="/evaluations" className="text-xs font-medium text-brand-600 hover:underline">Evaluations</Link>} />
          {stats.isLoading ? (
            <Spinner />
          ) : !lastEval ? (
            <EmptyState icon={<FlaskConical className="h-6 w-6" />} title="No evaluation runs" description="Run a RAGAS evaluation to measure faithfulness, relevancy and retrieval quality." />
          ) : (
            <div className="space-y-3 px-5 py-4">
              <div className="flex items-center justify-between">
                <Link to={`/evaluations/${lastEval.evaluation_id}`} className="font-mono text-xs text-brand-600 hover:underline">
                  {lastEval.evaluation_id.slice(0, 12)}
                </Link>
                <Badge tone={statusTone(lastEval.status)}>{lastEval.status}</Badge>
              </div>
              <p className="text-xs text-slate-500">
                {lastEval.dataset} · {lastEval.completed_cases}/{lastEval.total_cases} cases · {formatDate(lastEval.created_at)}
              </p>
              {Object.keys(lastEval.metrics).length === 0 ? (
                <p className="text-sm text-slate-500">No metric scores recorded for this run.</p>
              ) : (
                <dl className="grid grid-cols-2 gap-3">
                  {Object.entries(lastEval.metrics).map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-xs text-slate-500">{metricLabel(k)}</dt>
                      <dd className="text-lg font-semibold tabular-nums">{formatScore(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
