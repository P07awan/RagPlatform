import clsx from 'clsx';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Fragment, useState } from 'react';
import type { EvaluationCaseResult } from '../../types/api';
import { formatMs, formatScore, metricLabel } from '../../utils/format';
import { Badge } from '../ui';

function scoreClass(v: number | null | undefined) {
  if (v === null || v === undefined) return 'text-slate-400';
  if (v >= 0.8) return 'text-emerald-600 dark:text-emerald-400';
  if (v >= 0.5) return 'text-amber-600 dark:text-amber-400';
  return 'text-red-600 dark:text-red-400';
}

export function ResultsTable({ items, metricKeys, showFailedOnly }: { items: EvaluationCaseResult[]; metricKeys: string[]; showFailedOnly: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  const rows = showFailedOnly ? items.filter((r) => r.error) : items;
  if (rows.length === 0) return <p className="px-5 py-6 text-sm text-slate-500">No cases to show.</p>;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-xs text-slate-500 uppercase dark:border-slate-800">
          <tr>
            <th className="w-8 px-3 py-2" />
            <th className="px-3 py-2 font-medium">Question</th>
            {metricKeys.map((k) => (
              <th key={k} className="px-3 py-2 text-right font-medium whitespace-nowrap">{metricLabel(k)}</th>
            ))}
            <th className="px-3 py-2 text-right font-medium">Latency</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {rows.map((r) => {
            const expanded = open === r.case_index;
            return (
              <Fragment key={r.case_index}>
                <tr className={clsx('cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50', expanded && 'bg-slate-50 dark:bg-slate-800/50')} onClick={() => setOpen(expanded ? null : r.case_index)}>
                  <td className="px-3 py-2 text-slate-400">
                    <button aria-label={expanded ? 'Collapse case' : 'Expand case'} aria-expanded={expanded}>
                      {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </button>
                  </td>
                  <td className="max-w-md px-3 py-2">
                    <p className="truncate">{r.question}</p>
                    {r.error && <Badge tone="red">failed</Badge>}
                  </td>
                  {metricKeys.map((k) => (
                    <td key={k} className={clsx('px-3 py-2 text-right font-medium tabular-nums', scoreClass(r.scores[k]))}>
                      {formatScore(r.scores[k], 2)}
                    </td>
                  ))}
                  <td className="px-3 py-2 text-right text-slate-500 tabular-nums">{formatMs(r.latency_ms)}</td>
                </tr>
                {expanded && (
                  <tr>
                    <td colSpan={metricKeys.length + 3} className="bg-slate-50 px-6 py-4 dark:bg-slate-900/60">
                      {r.error && <p className="mb-3 rounded bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950/40 dark:text-red-300">Error: {r.error}</p>}
                      <div className="grid gap-4 md:grid-cols-2">
                        <div>
                          <h4 className="mb-1 text-xs font-semibold text-slate-500 uppercase">Reference answer</h4>
                          <p className="text-sm whitespace-pre-wrap">{r.reference_answer ?? '—'}</p>
                        </div>
                        <div>
                          <h4 className="mb-1 text-xs font-semibold text-slate-500 uppercase">Generated answer</h4>
                          <p className="text-sm whitespace-pre-wrap">{r.generated_answer ?? '—'}</p>
                        </div>
                      </div>
                      <h4 className="mt-4 mb-1 text-xs font-semibold text-slate-500 uppercase">Retrieved contexts ({r.retrieved_contexts.length})</h4>
                      <ol className="space-y-2">
                        {r.retrieved_contexts.map((c, i) => (
                          <li key={i} className="rounded border border-slate-200 bg-white p-2 text-xs whitespace-pre-wrap dark:border-slate-800 dark:bg-slate-950">
                            <span className="mr-1 font-mono text-slate-400">[{i + 1}]</span>
                            {c}
                          </li>
                        ))}
                      </ol>
                      {r.reference_contexts.length > 0 && (
                        <>
                          <h4 className="mt-4 mb-1 text-xs font-semibold text-slate-500 uppercase">Reference contexts</h4>
                          <ul className="list-disc space-y-1 pl-5 text-xs text-slate-600 dark:text-slate-400">
                            {r.reference_contexts.map((c, i) => <li key={i}>{c}</li>)}
                          </ul>
                        </>
                      )}
                      {Object.keys(r.scores).length > 0 && (
                        <p className="mt-3 text-xs text-slate-500">
                          {Object.entries(r.scores).map(([k, v]) => `${metricLabel(k)}: ${formatScore(v)}`).join(' · ')}
                        </p>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
