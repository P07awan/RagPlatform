import clsx from 'clsx';
import { UploadCloud, X } from 'lucide-react';
import { useRef, useState, type DragEvent } from 'react';
import { validateFiles, type RejectedFile } from '../../utils/fileValidation';
import { ALLOWED_EXTENSIONS, formatBytes } from '../../utils/format';
import { Button } from '../ui';

export function UploadDropzone({
  maxBytes,
  maxFiles = 10,
  disabled,
  uploading,
  progress,
  onUpload,
}: {
  maxBytes: number;
  maxFiles?: number;
  disabled?: boolean;
  uploading: boolean;
  progress: number | null;
  onUpload: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [selected, setSelected] = useState<File[]>([]);
  const [rejected, setRejected] = useState<RejectedFile[]>([]);

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const { accepted, rejected: bad } = validateFiles([...selected, ...Array.from(list)], maxBytes, maxFiles);
    setSelected(accepted);
    setRejected(bad);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (!disabled && !uploading) addFiles(e.dataTransfer.files);
  };

  const start = () => {
    if (selected.length === 0) return;
    onUpload(selected);
    setSelected([]);
    setRejected([]);
  };

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={clsx(
          'flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors',
          dragging ? 'border-brand-500 bg-brand-50 dark:bg-brand-500/10' : 'border-slate-300 dark:border-slate-700',
          disabled && 'opacity-60',
        )}
      >
        <UploadCloud className="h-8 w-8 text-slate-400" aria-hidden />
        <p className="mt-3 text-sm font-medium">Drag and drop files here</p>
        <p className="mt-1 text-xs text-slate-500">
          PDF, TXT or Markdown · up to {formatBytes(maxBytes)} each · max {maxFiles} files
        </p>
        <Button variant="secondary" className="mt-4" onClick={() => inputRef.current?.click()} disabled={disabled || uploading}>
          Choose files
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ALLOWED_EXTENSIONS.join(',')}
          className="hidden"
          data-testid="file-input"
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = '';
          }}
        />
      </div>

      {rejected.length > 0 && (
        <ul role="alert" className="mt-3 space-y-1 text-xs text-red-600 dark:text-red-400">
          {rejected.map((r) => (
            <li key={r.name + r.reason}>
              <span className="font-medium">{r.name}</span>: {r.reason}
            </li>
          ))}
        </ul>
      )}

      {selected.length > 0 && (
        <div className="mt-4">
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {selected.map((f) => (
              <li key={f.name + f.size} className="flex items-center justify-between px-3 py-2 text-sm">
                <span className="truncate">{f.name}</span>
                <span className="flex items-center gap-3 text-xs text-slate-500">
                  {formatBytes(f.size)}
                  <button aria-label={`Remove ${f.name}`} onClick={() => setSelected((s) => s.filter((x) => x !== f))} className="rounded p-0.5 hover:bg-slate-100 dark:hover:bg-slate-800">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex justify-end">
            <Button onClick={start} loading={uploading} disabled={disabled}>
              Upload {selected.length} file{selected.length === 1 ? '' : 's'}
            </Button>
          </div>
        </div>
      )}

      {uploading && progress !== null && (
        <div className="mt-4" aria-label="Upload progress">
          <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
            <div className="h-full bg-brand-600 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
          <p className="mt-1 text-xs text-slate-500">{progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : 'Upload complete, waiting for server…'}</p>
        </div>
      )}
    </div>
  );
}
