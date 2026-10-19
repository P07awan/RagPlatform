import { BookOpen, FileText } from 'lucide-react';
import type { ChatMessage } from '../../hooks/useChatStream';
import { formatScore } from '../../utils/format';
import { Badge, EmptyState } from '../ui';

function pageLabel(page: number | null) {
  return page === null ? 'page n/a' : `page ${page}`;
}

export function SourcesPanel({ message }: { message: ChatMessage | null }) {
  if (!message) {
    return <EmptyState icon={<BookOpen className="h-6 w-6" />} title="No sources yet" description="Citations and retrieved excerpts for the selected answer appear here." />;
  }
  const citations = message.citations ?? [];
  const cited = new Set(citations.map((c) => c.chunk_id));
  const chunks = message.chunks ?? [];

  return (
    <div className="space-y-5 p-4">
      <section>
        <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">Citations ({citations.length})</h3>
        {citations.length === 0 ? (
          <p className="text-sm text-slate-500">{message.status === 'streaming' ? 'Waiting for the answer…' : 'The answer did not cite any source.'}</p>
        ) : (
          <ol className="space-y-2">
            {citations.map((c) => (
              <li key={c.chunk_id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
                    <span className="rounded bg-brand-600 px-1.5 text-xs text-white">[{c.index}]</span>
                    <span className="truncate">{c.filename}</span>
                  </span>
                  <span className="shrink-0 text-xs text-slate-500">{pageLabel(c.page_number)}</span>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-slate-600 dark:text-slate-400">{c.excerpt}</p>
                <p className="mt-1 font-mono text-[10px] text-slate-400">chunk #{c.chunk_index} · {c.chunk_id.slice(0, 8)}</p>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">Retrieved context ({chunks.length})</h3>
        {chunks.length === 0 ? (
          <p className="text-sm text-slate-500">No retrieval details for this answer.</p>
        ) : (
          <ul className="space-y-2">
            {chunks.map((ch, i) => (
              <li key={ch.chunk_id}>
                <details className="group rounded-lg border border-slate-200 dark:border-slate-800">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-2 p-3 text-sm">
                    <span className="flex min-w-0 items-center gap-2">
                      <FileText className="h-4 w-4 shrink-0 text-slate-400" aria-hidden />
                      <span className="truncate">{i + 1}. {ch.filename}</span>
                    </span>
                    {cited.has(ch.chunk_id) && <Badge tone="green">cited</Badge>}
                  </summary>
                  <div className="border-t border-slate-100 p-3 dark:border-slate-800">
                    <dl className="mb-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-500">
                      <dt>Rerank</dt><dd className="tabular-nums">{formatScore(ch.rerank_score)}</dd>
                      <dt>Fused (RRF)</dt><dd className="tabular-nums">{formatScore(ch.fused_score, 4)}</dd>
                      <dt>Dense</dt><dd className="tabular-nums">{ch.dense_rank ? `#${ch.dense_rank} · ${formatScore(ch.dense_score)}` : '—'}</dd>
                      <dt>BM25</dt><dd className="tabular-nums">{ch.bm25_rank ? `#${ch.bm25_rank} · ${formatScore(ch.bm25_score, 2)}` : '—'}</dd>
                      <dt>Location</dt><dd>{pageLabel(ch.page_number)}</dd>
                    </dl>
                    <p className="max-h-60 overflow-y-auto text-xs leading-relaxed whitespace-pre-wrap text-slate-700 dark:text-slate-300">{ch.content}</p>
                  </div>
                </details>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
