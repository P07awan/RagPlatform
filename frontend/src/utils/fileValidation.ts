import { ALLOWED_EXTENSIONS, fileExtension, formatBytes } from './format';

export interface RejectedFile {
  name: string;
  reason: string;
}

export function validateFiles(files: File[], maxBytes: number, maxFiles: number): { accepted: File[]; rejected: RejectedFile[] } {
  const accepted: File[] = [];
  const rejected: RejectedFile[] = [];
  for (const f of files) {
    const ext = fileExtension(f.name);
    if (!ALLOWED_EXTENSIONS.includes(ext)) rejected.push({ name: f.name, reason: `Unsupported type "${ext || 'none'}"` });
    else if (f.size === 0) rejected.push({ name: f.name, reason: 'File is empty' });
    else if (f.size > maxBytes) rejected.push({ name: f.name, reason: `Exceeds ${formatBytes(maxBytes)} limit` });
    else if (accepted.length >= maxFiles) rejected.push({ name: f.name, reason: `Max ${maxFiles} files per upload` });
    else accepted.push(f);
  }
  return { accepted, rejected };
}
