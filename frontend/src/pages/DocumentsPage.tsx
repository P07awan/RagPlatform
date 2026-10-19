import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileText } from 'lucide-react';
import { useState } from 'react';
import { deleteDocument, listDocuments, uploadDocuments } from '../api/documents';
import { DocumentTable } from '../components/documents/DocumentTable';
import { RetrievalInspector } from '../components/documents/RetrievalInspector';
import { UploadDropzone } from '../components/documents/UploadDropzone';
import { PageHeader } from '../components/layout/PageHeader';
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Modal, Spinner } from '../components/ui';
import { queryKeys, useConfig } from '../hooks/useSystem';
import type { DocumentOut, UploadResponse } from '../types/api';

const PAGE_SIZE = 20;

const outcomeTone = { accepted: 'blue', indexed: 'green', duplicate: 'gray', rejected: 'red', failed: 'red' } as const;

export function DocumentsPage() {
  const qc = useQueryClient();
  const config = useConfig();
  const [offset, setOffset] = useState(0);
  const [progress, setProgress] = useState<number | null>(null);
  const [lastUpload, setLastUpload] = useState<UploadResponse | null>(null);
  const [toDelete, setToDelete] = useState<DocumentOut | null>(null);

  const docs = useQuery({
    queryKey: queryKeys.documents(offset),
    queryFn: () => listDocuments({ limit: PAGE_SIZE, offset }),
    // Poll while anything is still being ingested so statuses update live.
    refetchInterval: (q) => (q.state.data?.items.some((d) => d.status === 'pending' || d.status === 'processing') ? 2000 : false),
  });

  const upload = useMutation({
    mutationFn: (files: File[]) => uploadDocuments(files, setProgress),
    onSuccess: (res) => {
      setLastUpload(res);
      setOffset(0);
    },
    onSettled: () => {
      setProgress(null);
      void qc.invalidateQueries({ queryKey: ['documents'] });
      void qc.invalidateQueries({ queryKey: queryKeys.stats });
    },
  });

  const remove = useMutation({
    mutationFn: (doc: DocumentOut) => deleteDocument(doc.document_id),
    onSuccess: () => setToDelete(null),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['documents'] });
      void qc.invalidateQueries({ queryKey: queryKeys.stats });
    },
  });

  const maxBytes = (config.data?.max_upload_size_mb ?? 20) * 1024 * 1024;
  const openaiMissing = config.data ? !config.data.openai_configured : false;
  const total = docs.data?.total ?? 0;

  return (
    <>
      <PageHeader title="Documents" description="Upload, index and manage the documents used to answer questions." />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[400px_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader title="Upload documents" description="Files are validated, chunked, embedded and stored in Qdrant." />
          <div className="p-5">
            {openaiMissing && (
              <p className="mb-4 rounded-lg bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                Uploads are disabled: OPENAI_API_KEY is not configured on the backend (needed for embeddings).
              </p>
            )}
            <UploadDropzone maxBytes={maxBytes} disabled={openaiMissing} uploading={upload.isPending} progress={progress} onUpload={(f) => upload.mutate(f)} />
            {upload.isError && <ErrorState error={upload.error} />}
            {lastUpload && (
              <div className="mt-4 space-y-2" aria-label="Upload results">
                <p className="text-xs font-semibold text-slate-500 uppercase">Last upload</p>
                {lastUpload.results.map((r) => (
                  <div key={r.filename + (r.document_id ?? '')} className="rounded-lg border border-slate-200 p-2 text-xs dark:border-slate-800">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{r.filename}</span>
                      <Badge tone={outcomeTone[r.outcome]}>{r.outcome}</Badge>
                    </div>
                    {r.message && <p className="mt-1 text-slate-500">{r.message}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Indexed documents" description={docs.data ? `${total} document${total === 1 ? '' : 's'}` : undefined} />
          {docs.isLoading ? (
            <Spinner label="Loading documents…" />
          ) : docs.isError ? (
            <ErrorState error={docs.error} onRetry={() => docs.refetch()} />
          ) : !docs.data?.items.length ? (
            <EmptyState icon={<FileText className="h-6 w-6" />} title="No documents uploaded" description="Upload your first PDF, TXT or Markdown file to start asking questions." />
          ) : (
            <>
              <DocumentTable documents={docs.data.items} onDelete={setToDelete} />
              {total > PAGE_SIZE && (
                <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3 text-xs text-slate-500 dark:border-slate-800">
                  <span>
                    {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}>Previous</Button>
                    <Button variant="secondary" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset((o) => o + PAGE_SIZE)}>Next</Button>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>
      </div>

      <div className="mt-6">
        <RetrievalInspector disabled={openaiMissing} />
      </div>

      <Modal open={toDelete !== null} title="Delete document?" onClose={() => !remove.isPending && setToDelete(null)}>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          <span className="font-medium text-slate-900 dark:text-slate-100">{toDelete?.filename}</span> and all of its vectors will be permanently removed from the index.
        </p>
        {remove.isError && <ErrorState error={remove.error} />}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setToDelete(null)} disabled={remove.isPending}>Cancel</Button>
          <Button variant="danger" loading={remove.isPending} onClick={() => toDelete && remove.mutate(toDelete)}>Delete</Button>
        </div>
      </Modal>
    </>
  );
}
