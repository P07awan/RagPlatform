import { useQueryClient } from '@tanstack/react-query';
import { statusTone } from '../utils/status';
import { CheckCircle2, KeyRound, XCircle } from 'lucide-react';
import { useState, type FormEvent, type ReactNode } from 'react';
import { API_BASE_URL, setApiKey } from '../api/client';
import { PageHeader } from '../components/layout/PageHeader';
import { Badge, Button, Card, CardHeader, ErrorState, Spinner } from '../components/ui';
import { useApiKeyState, useConfig, useHealth } from '../hooks/useSystem';

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-3 text-sm">
      <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="text-right font-medium break-all">{children}</dd>
    </div>
  );
}

function Bool({ value, on = 'enabled', off = 'disabled' }: { value: boolean; on?: string; off?: string }) {
  return value ? (
    <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
      <CheckCircle2 className="h-4 w-4" aria-hidden /> {on}
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-slate-500">
      <XCircle className="h-4 w-4" aria-hidden /> {off}
    </span>
  );
}

export function SettingsPage() {
  const qc = useQueryClient();
  const health = useHealth();
  const config = useConfig();
  const storedKey = useApiKeyState();
  const [draft, setDraft] = useState('');

  const saveKey = (e: FormEvent) => {
    e.preventDefault();
    setApiKey(draft.trim() || null);
    setDraft('');
    void qc.invalidateQueries();
  };

  const c = config.data;
  return (
    <>
      <PageHeader title="Settings" description="Backend connection and non-sensitive configuration. Secret values are never displayed." />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader title="Backend connection" />
          <dl className="divide-y divide-slate-100 dark:divide-slate-800">
            <Row label="API base URL">
              <span className="font-mono text-xs">{API_BASE_URL}</span>
            </Row>
            <Row label="Status">
              {health.isLoading ? '…' : health.isError ? <Badge tone="red">unreachable</Badge> : <Badge tone={statusTone(health.data!.status)}>{health.data!.status}</Badge>}
            </Row>
            {health.data &&
              Object.entries(health.data.components).map(([name, s]) => (
                <Row key={name} label={name}>
                  <span className="flex flex-col items-end gap-0.5">
                    <Badge tone={statusTone(s.status)}>{s.status}</Badge>
                    {s.detail && <span className="text-xs font-normal text-slate-500">{s.detail}</span>}
                  </span>
                </Row>
              ))}
          </dl>
          {health.isError && <ErrorState error={health.error} onRetry={() => health.refetch()} />}
        </Card>

        <Card>
          <CardHeader title="Application API key" description="Stored only in this browser (localStorage) and sent as the X-API-Key header." />
          <form onSubmit={saveKey} className="space-y-3 p-5">
            <p className="flex items-center gap-2 text-sm">
              <KeyRound className="h-4 w-4 text-slate-400" aria-hidden />
              {storedKey ? `Key set (••••${storedKey.slice(-4)})` : 'No key set'}
              {c && <span className="text-xs text-slate-500">· server auth {c.auth_enabled ? 'required' : 'disabled'}</span>}
            </p>
            <label htmlFor="api-key" className="sr-only">API key</label>
            <input
              id="api-key"
              type="password"
              autoComplete="off"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Paste application API key"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            />
            <div className="flex gap-2">
              <Button type="submit" disabled={!draft.trim()}>Save key</Button>
              <Button variant="secondary" disabled={!storedKey} onClick={() => { setApiKey(null); void qc.invalidateQueries(); }}>
                Remove key
              </Button>
            </div>
            <p className="text-xs text-slate-500">
              This is the single-user portfolio auth model. Never paste an OpenAI key here — the OpenAI key lives only on the backend.
            </p>
          </form>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader title="RAG configuration" />
          {config.isLoading ? (
            <Spinner />
          ) : config.isError ? (
            <ErrorState error={config.error} onRetry={() => config.refetch()} />
          ) : c ? (
            <dl className="grid grid-cols-1 divide-y divide-slate-100 md:grid-cols-2 md:divide-y-0 dark:divide-slate-800">
              <div className="divide-y divide-slate-100 dark:divide-slate-800">
                <Row label="Environment">{c.environment}</Row>
                <Row label="LLM model"><span className="font-mono text-xs">{c.llm_model}</span></Row>
                <Row label="Embedding model"><span className="font-mono text-xs">{c.embedding_model} ({c.vector_size}d)</span></Row>
                <Row label="OpenAI key"><Bool value={c.openai_configured} on="configured" off="not configured" /></Row>
                <Row label="Qdrant collection"><span className="font-mono text-xs">{c.collection}</span></Row>
                <Row label="Chunk size / overlap">{c.chunk_size} / {c.chunk_overlap}</Row>
                <Row label="Max upload size">{c.max_upload_size_mb} MB</Row>
              </div>
              <div className="divide-y divide-slate-100 dark:divide-slate-800">
                <Row label="Retrieval top-k / rerank top-k">{c.retrieval_top_k} / {c.rerank_top_k}</Row>
                <Row label="RRF k">{c.rrf_k}</Row>
                <Row label="Reranker"><Bool value={c.reranker_enabled} /></Row>
                <Row label="Reranker model"><span className="font-mono text-xs">{c.reranker_model}</span></Row>
                <Row label="Reranker state"><Badge tone={statusTone(c.reranker_state)}>{c.reranker_state}</Badge> <span className="text-xs text-slate-500">fallback: {c.reranker_fallback}</span></Row>
                <Row label="Redis cache"><Bool value={c.cache_enabled} /></Row>
                <Row label="LangSmith tracing"><Bool value={c.tracing_enabled} />{c.tracing_enabled && c.langsmith_project ? <span className="ml-2 font-mono text-xs">{c.langsmith_project}</span> : null}</Row>
              </div>
            </dl>
          ) : null}
          {c && c.warnings.length > 0 && (
            <ul className="m-5 list-disc space-y-1 rounded-lg bg-amber-50 py-3 pr-3 pl-8 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
              {c.warnings.map((w) => <li key={w}>{w}</li>)}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
