import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router';
import { vi } from 'vitest';
import type { ConfigStatus, HealthResponse } from '../src/types/api';

export function renderWithProviders(ui: ReactElement, { route = '/' }: { route?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

type Handler = (url: URL, init?: RequestInit) => Response | Promise<Response>;

/** Route fetch calls by "METHOD /path" (path relative to /api/v1). Unmatched → 404. */
export function mockFetch(routes: Record<string, Handler>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
    const method = (init?.method ?? 'GET').toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, '');
    const handler = routes[`${method} ${path}`];
    if (!handler) return json({ error: { code: 'not_found', message: `no mock for ${method} ${path}` } }, 404);
    return handler(url, init);
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

export const health: HealthResponse = {
  status: 'ok',
  version: '1.0.0',
  environment: 'development',
  components: {
    qdrant: { status: 'ok', detail: null },
    openai: { status: 'ok', detail: null },
    reranker: { status: 'ok', detail: 'Loads on first use' },
    cache: { status: 'disabled', detail: null },
    tracing: { status: 'disabled', detail: null },
  },
};

export const config: ConfigStatus = {
  environment: 'development',
  llm_model: 'gpt-4o-mini',
  embedding_model: 'text-embedding-3-small',
  vector_size: 1536,
  collection: 'rag_documents',
  chunk_size: 800,
  chunk_overlap: 120,
  retrieval_top_k: 10,
  rerank_top_k: 4,
  rrf_k: 60,
  reranker_enabled: true,
  reranker_model: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
  reranker_fallback: 'error',
  reranker_state: 'not_loaded',
  cache_enabled: false,
  tracing_enabled: false,
  langsmith_project: null,
  auth_enabled: false,
  openai_configured: true,
  max_upload_size_mb: 20,
  allowed_extensions: ['.markdown', '.md', '.pdf', '.txt'],
  warnings: [],
};

export const emptyStats = {
  documents_total: 0,
  documents_by_status: {},
  chunks_indexed: 0,
  recent_documents: [],
  recent_chats: [],
  last_evaluation: null,
};

export function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

export const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
