import { useMutation } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { searchRetrieval } from '../../api/retrieval';
import { formatMs, formatScore } from '../../utils/format';
import { Badge, Button, Card, CardHeader, ErrorState } from '../ui';

/** Runs hybrid retrieval + reranking without calling the LLM (costs one embedding call). */
export function RetrievalInspector({ disabled }: { disabled?: boolean }) {
  const [query, setQuery] = useState('');
  const [rerank, setRerank] = useState(true);
  const search = useMutation({ mutationFn: () => searchRetrieval({ query: query.trim(), rerank }) });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (query.trim()) search.mutate();
  };

  const data = search.data;
  return (
    <Card>
      <CardHeader title="Retrieval inspector" description="See which chunks hybrid search and the reranker select for a query — no answer generation." />
      <form onSubmit={submit} className="flex flex-col gap-2 p-5 sm:flex-row sm:items-center">
        <label htmlFor="retrieval-query" className="sr-only">Query</label>
        <input
          id="retrieval-query"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. What is the default chunk size?"
          maxLength={2000}
          className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
        />
        <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
          <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} /> Rerank
        </label>
        <Button type="submit" disabled={disabled || !query.trim()} loading={search.isPending}>
          <Search className="h-4 w-4" aria-hidden /> Search
        </Button>
      </form>
      {search.isError && <ErrorState error={search.error} />}
      {data && (
        <div className="border-t border-slate-100 px-5 py-4 dark:border-slate-800">
          <div className="mb-3 flex flex-wrap gap-2 text-xs text-slate-500">
            <span>dense {data.dense_candidates}</span>·<span>bm25 {data.bm25_candidates}</span>·<span>fused {data.fused.length}</span>·
            <Badge tone={data.rerank_applied ? 'green' : 'yellow'}>rerank: {data.rerank_mode}</Badge>
            {Object.entries(data.latency_ms).map(([k, v]) => (
              <span key={k}>{k.replace('_ms', '')} {formatMs(v)}</span>
            ))}
          </div>
          {data.reranked.length === 0 ? (
            <p className="text-sm text-slate-500">No chunks matched this query.</p>
          ) : (
            <ol className="space-y-2">
              {data.reranked.map((c, i) => (
                <li key={c.chunk_id} className="rounded-lg border border-slate-200 p-3 text-xs dark:border-slate-800">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">
                      {i + 1}. {c.filename} <span className="text-slate-400">· {c.page_number === null ? 'page n/a' : `page ${c.page_number}`}</span>
                    </span>
                    <span className="text-slate-500 tabular-nums">
                      rerank {formatScore(c.rerank_score)} · rrf {formatScore(c.fused_score, 4)} · dense #{c.dense_rank ?? '—'} · bm25 #{c.bm25_rank ?? '—'}
                    </span>
                  </div>
                  <p className="mt-2 line-clamp-4 whitespace-pre-wrap text-slate-600 dark:text-slate-400">{c.content}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </Card>
  );
}
