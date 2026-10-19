import { Loader2, Trash2 } from 'lucide-react';
import { statusTone } from '../../utils/status';
import type { DocumentOut } from '../../types/api';
import { formatBytes, formatDate } from '../../utils/format';
import { Badge } from '../ui';

export function DocumentTable({ documents, onDelete }: { documents: DocumentOut[]; onDelete: (doc: DocumentOut) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-xs text-slate-500 uppercase dark:border-slate-800">
          <tr>
            <th className="px-5 py-3 font-medium">Document</th>
            <th className="px-3 py-3 font-medium">Status</th>
            <th className="hidden px-3 py-3 font-medium md:table-cell">Size</th>
            <th className="hidden px-3 py-3 font-medium md:table-cell">Chunks</th>
            <th className="hidden px-3 py-3 font-medium lg:table-cell">Pages</th>
            <th className="hidden px-3 py-3 font-medium lg:table-cell">Uploaded</th>
            <th className="px-5 py-3 text-right font-medium">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {documents.map((d) => (
            <tr key={d.document_id} className="align-top">
              <td className="max-w-xs px-5 py-3">
                <p className="truncate font-medium" title={d.filename}>{d.filename}</p>
                <p className="font-mono text-[11px] text-slate-400">{d.document_id}</p>
                {d.status === 'failed' && d.error && (
                  <p className="mt-1 text-xs text-red-600 dark:text-red-400">
                    {d.error} <span className="text-slate-500">Re-upload the file to retry.</span>
                  </p>
                )}
              </td>
              <td className="px-3 py-3">
                <Badge tone={statusTone(d.status)}>
                  {(d.status === 'processing' || d.status === 'pending') && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
                  {d.status}
                </Badge>
              </td>
              <td className="hidden px-3 py-3 text-slate-600 tabular-nums md:table-cell dark:text-slate-400">{formatBytes(d.size_bytes)}</td>
              <td className="hidden px-3 py-3 text-slate-600 tabular-nums md:table-cell dark:text-slate-400">{d.chunk_count}</td>
              <td className="hidden px-3 py-3 text-slate-600 tabular-nums lg:table-cell dark:text-slate-400">{d.page_count ?? '—'}</td>
              <td className="hidden px-3 py-3 text-slate-600 lg:table-cell dark:text-slate-400">{formatDate(d.created_at)}</td>
              <td className="px-5 py-3 text-right">
                <button
                  onClick={() => onDelete(d)}
                  disabled={d.status === 'processing' || d.status === 'pending'}
                  aria-label={`Delete ${d.filename}`}
                  title={d.status === 'processing' ? 'Cannot delete while processing' : 'Delete document'}
                  className="rounded-lg p-2 text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40 dark:hover:bg-red-950/40"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
