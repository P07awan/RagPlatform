import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import * as documentsApi from '../src/api/documents';
import { validateFiles } from '../src/utils/fileValidation';
import { DocumentsPage } from '../src/pages/DocumentsPage';
import type { DocumentOut } from '../src/types/api';
import { config, json, mockFetch, renderWithProviders } from './utils';

const doc = (over: Partial<DocumentOut> = {}): DocumentOut => ({
  document_id: 'abc123',
  filename: 'guide.md',
  file_type: 'markdown',
  size_bytes: 2048,
  content_hash: 'h',
  status: 'indexed',
  error: null,
  chunk_count: 12,
  page_count: null,
  embedding_model: 'text-embedding-3-small',
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
  indexed_at: '2026-10-01T10:00:05Z',
  ...over,
});

const file = (name: string, size = 10, type = 'text/plain') => new File(['x'.repeat(size)], name, { type });

describe('validateFiles', () => {
  it('rejects unsupported types, empty and oversized files', () => {
    const { accepted, rejected } = validateFiles(
      [file('a.md'), file('b.exe'), file('c.txt', 0), file('d.pdf', 2000)],
      1000,
      10,
    );
    expect(accepted.map((f) => f.name)).toEqual(['a.md']);
    expect(rejected.map((r) => r.name)).toEqual(['b.exe', 'c.txt', 'd.pdf']);
  });

  it('enforces the max file count', () => {
    const files = Array.from({ length: 3 }, (_, i) => file(`f${i}.txt`));
    expect(validateFiles(files, 1000, 2).rejected).toHaveLength(1);
  });
});

describe('DocumentsPage', () => {
  it('shows the empty state', async () => {
    mockFetch({
      'GET /config': () => json(config),
      'GET /documents': () => json({ items: [], total: 0, limit: 20, offset: 0 }),
    });
    renderWithProviders(<DocumentsPage />);
    expect(await screen.findByText('No documents uploaded')).toBeInTheDocument();
  });

  it('lists documents with status and failure details', async () => {
    mockFetch({
      'GET /config': () => json(config),
      'GET /documents': () =>
        json({
          items: [doc(), doc({ document_id: 'f1', filename: 'scan.pdf', status: 'failed', error: 'No extractable text found. OCR is not configured.' })],
          total: 2,
          limit: 20,
          offset: 0,
        }),
    });
    renderWithProviders(<DocumentsPage />);
    expect(await screen.findByText('guide.md')).toBeInTheDocument();
    expect(screen.getByText('indexed')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.getByText(/OCR is not configured/)).toBeInTheDocument();
  });

  it('shows API errors with a retry action', async () => {
    mockFetch({
      'GET /config': () => json(config),
      'GET /documents': () => json({ error: { code: 'unauthorized', message: 'Invalid API key', request_id: 'r1' } }, 401),
    });
    renderWithProviders(<DocumentsPage />);
    expect(await screen.findByText('Invalid API key')).toBeInTheDocument();
    expect(screen.getByText(/Set a valid API key/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('validates selected files and uploads the accepted ones', async () => {
    mockFetch({
      'GET /config': () => json(config),
      'GET /documents': () => json({ items: [], total: 0, limit: 20, offset: 0 }),
    });
    const upload = vi.spyOn(documentsApi, 'uploadDocuments').mockResolvedValue({
      results: [{ filename: 'notes.md', outcome: 'accepted', document_id: 'n1', message: 'Queued for ingestion', document: null }],
      accepted: 1,
      rejected: 0,
    });
    const user = userEvent.setup({ applyAccept: false });
    renderWithProviders(<DocumentsPage />);
    await screen.findByText('No documents uploaded');

    const input = screen.getByTestId('file-input');
    await user.upload(input, [file('notes.md', 50), file('virus.exe', 50)]);
    expect(screen.getByText(/Unsupported type ".exe"/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Upload 1 file' }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(upload.mock.calls[0][0].map((f: File) => f.name)).toEqual(['notes.md']);
    expect(await screen.findByText('Queued for ingestion')).toBeInTheDocument();
  });

  it('requires confirmation before deleting', async () => {
    const fetchFn = mockFetch({
      'GET /config': () => json(config),
      'GET /documents': () => json({ items: [doc()], total: 1, limit: 20, offset: 0 }),
      'DELETE /documents/abc123': () => json({ document_id: 'abc123', deleted: true, vectors_deleted: true }),
    });
    const user = userEvent.setup();
    renderWithProviders(<DocumentsPage />);
    await user.click(await screen.findByRole('button', { name: 'Delete guide.md' }));
    expect(screen.getByRole('dialog', { name: 'Delete document?' })).toBeInTheDocument();
    expect(fetchFn.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false);
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(fetchFn.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true));
  });

  it('disables uploads when the backend has no OpenAI key', async () => {
    mockFetch({
      'GET /config': () => json({ ...config, openai_configured: false }),
      'GET /documents': () => json({ items: [], total: 0, limit: 20, offset: 0 }),
    });
    renderWithProviders(<DocumentsPage />);
    expect(await screen.findByText(/Uploads are disabled/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Choose files' })).toBeDisabled();
    fireEvent.drop(screen.getByText('Drag and drop files here'));
  });
});
