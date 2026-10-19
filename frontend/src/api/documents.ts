import type { DocumentList, DocumentOut, DocumentStatus, UploadResponse } from '../types/api';
import { ApiError, apiRequest, buildUrl, getApiKey, API_BASE_URL } from './client';

export function listDocuments(params: { limit?: number; offset?: number; status?: DocumentStatus } = {}) {
  return apiRequest<DocumentList>('/documents', { query: { limit: params.limit ?? 50, offset: params.offset ?? 0, status: params.status } });
}

export function getDocument(documentId: string) {
  return apiRequest<DocumentOut>(`/documents/${encodeURIComponent(documentId)}`);
}

export function deleteDocument(documentId: string) {
  return apiRequest<{ document_id: string; deleted: boolean; vectors_deleted: boolean }>(
    `/documents/${encodeURIComponent(documentId)}`,
    { method: 'DELETE' },
  );
}

/** Multipart upload via XHR so we can report upload progress (fetch cannot). */
export function uploadDocuments(
  files: File[],
  onProgress?: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', buildUrl('/documents/upload'));
    const key = getApiKey();
    if (key) xhr.setRequestHeader('X-API-Key', key);
    xhr.responseType = 'json';
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      const body = xhr.response as { error?: { code: string; message: string; request_id?: string } } | UploadResponse | null;
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as UploadResponse);
      } else {
        const err = (body as { error?: { code: string; message: string; request_id?: string } } | null)?.error;
        reject(new ApiError(xhr.status, err?.code ?? 'http_error', err?.message ?? `Upload failed (HTTP ${xhr.status})`, err?.request_id ?? null));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, 'network_error', `Cannot reach the backend at ${API_BASE_URL}.`));
    xhr.onabort = () => reject(new DOMException('Upload aborted', 'AbortError'));
    signal?.addEventListener('abort', () => xhr.abort(), { once: true });
    const form = new FormData();
    for (const f of files) form.append('files', f, f.name);
    xhr.send(form);
  });
}
