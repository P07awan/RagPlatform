import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { ChatPage } from '../src/pages/ChatPage';
import type { ChatResponse, RetrievedChunk } from '../src/types/api';
import { config, json, mockFetch, renderWithProviders, sse, sseResponse } from './utils';

const chunk: RetrievedChunk = {
  chunk_id: 'chunk-1',
  document_id: 'doc-1',
  filename: 'guide.md',
  chunk_index: 3,
  page_number: null,
  content: 'The default chunk size is 800 characters with an overlap of 120 characters.',
  dense_score: 0.81,
  dense_rank: 1,
  bm25_score: 7.2,
  bm25_rank: 1,
  fused_score: 0.0328,
  rerank_score: 8.1,
};

const metadata: ChatResponse = {
  answer: 'The default chunk size is 800 characters [1].',
  citations: [
    { index: 1, chunk_id: 'chunk-1', document_id: 'doc-1', filename: 'guide.md', page_number: null, chunk_index: 3, excerpt: chunk.content, score: 8.1 },
  ],
  session_id: 's1',
  request_id: 'req-1',
  insufficient_context: false,
  cache_hit: false,
  model: 'gpt-4o-mini',
  latency: { retrieval_ms: 120, rerank_ms: 40, generation_ms: 900, total_ms: 1100 },
  retrieval: { dense_candidates: 10, bm25_candidates: 8, fused_candidates: 10, reranked: true, rerank_mode: 'cross_encoder', chunks: [chunk] },
};

function streamFrames(): string[] {
  const full =
    sse('start', { request_id: 'req-1', session_id: 's1' }) +
    sse('sources', { chunks: [chunk], rerank_mode: 'cross_encoder', cache_hit: false }) +
    sse('token', { text: 'The default chunk size ' }) +
    sse('token', { text: 'is 800 characters [1].' }) +
    sse('metadata', metadata) +
    sse('done', {});
  // Split at awkward boundaries to exercise incremental parsing.
  const out: string[] = [];
  for (let i = 0; i < full.length; i += 37) out.push(full.slice(i, i + 37));
  return out;
}

describe('ChatPage', () => {
  it('streams an answer and shows citations', async () => {
    const fetchFn = mockFetch({
      'GET /config': () => json(config),
      'POST /chat/stream': () => sseResponse(streamFrames()),
    });
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    await user.type(screen.getByLabelText('Ask a question about your documents'), 'What is the default chunk size?');
    await user.click(screen.getByRole('button', { name: 'Send question' }));

    const answer = await screen.findByTestId('assistant-message');
    await waitFor(() => expect(answer).toHaveTextContent('The default chunk size is 800 characters [1].'));
    expect(await screen.findByText('1 citation · view sources')).toBeInTheDocument();
    const call = fetchFn.mock.calls.find(([url]) => String(url).endsWith('/chat/stream'));
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ question: 'What is the default chunk size?' });

    // Sources panel shows the citation and its page metadata honestly.
    expect(screen.getByText('[1]')).toBeInTheDocument();
    expect(screen.getAllByText('page n/a').length).toBeGreaterThan(0);
    expect(screen.getByText('Citations (1)')).toBeInTheDocument();
  });

  it('renders model output as text, never as HTML', async () => {
    mockFetch({
      'GET /config': () => json(config),
      'POST /chat/stream': () =>
        sseResponse([
          sse('start', { request_id: 'r', session_id: 's' }),
          sse('token', { text: '<img src=x onerror="alert(1)"><script>alert(2)</script>Safe text' }),
          sse('done', {}),
        ]),
    });
    const user = userEvent.setup();
    const { container } = renderWithProviders(<ChatPage />);
    await user.type(screen.getByLabelText('Ask a question about your documents'), 'xss?');
    await user.click(screen.getByRole('button', { name: 'Send question' }));
    await screen.findByText(/Safe text/);
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
  });

  it('shows stream errors with a retry button', async () => {
    mockFetch({
      'GET /config': () => json(config),
      'POST /chat/stream': () =>
        sseResponse([
          sse('start', { request_id: 'r', session_id: 's' }),
          sse('error', { code: 'upstream_quota_exceeded', message: 'OpenAI quota exhausted or billing not configured for this API key.' }),
          sse('done', {}),
        ]),
    });
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    await user.type(screen.getByLabelText('Ask a question about your documents'), 'q');
    await user.click(screen.getByRole('button', { name: 'Send question' }));
    expect(await screen.findByText(/OpenAI quota exhausted/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
  });

  it('detects an interrupted stream (no done event)', async () => {
    mockFetch({
      'GET /config': () => json(config),
      'POST /chat/stream': () => sseResponse([sse('start', { request_id: 'r', session_id: 's' }), sse('token', { text: 'partial' })]),
    });
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    await user.type(screen.getByLabelText('Ask a question about your documents'), 'q');
    await user.click(screen.getByRole('button', { name: 'Send question' }));
    expect(await screen.findByText(/interrupted before completion/)).toBeInTheDocument();
  });

  it('shows HTTP errors from the API', async () => {
    mockFetch({
      'GET /config': () => json(config),
      'POST /chat/stream': () => json({ error: { code: 'rate_limited', message: 'Rate limit exceeded (30 requests/minute)' } }, 429),
    });
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    await user.type(screen.getByLabelText('Ask a question about your documents'), 'q');
    await user.click(screen.getByRole('button', { name: 'Send question' }));
    expect(await screen.findByText(/Rate limit exceeded/)).toBeInTheDocument();
  });

  it('prevents duplicate submissions while streaming and allows cancelling', async () => {
    let release!: () => void;
    const fetchFn = mockFetch({
      'GET /config': () => json(config),
      'POST /chat/stream': (_url, init) =>
        new Promise<Response>((resolve, reject) => {
          release = () => resolve(sseResponse([sse('done', {})]));
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        }),
    });
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    const input = screen.getByLabelText('Ask a question about your documents');
    await user.type(input, 'first{Enter}');
    await screen.findByRole('button', { name: 'Stop generating' });
    await user.type(input, 'second{Enter}');
    expect(fetchFn.mock.calls.filter(([u]) => String(u).endsWith('/chat/stream'))).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: 'Stop generating' }));
    expect(await screen.findByText('Generation cancelled.')).toBeInTheDocument();
    release?.();
  });

  it('disables chat when the backend has no OpenAI key', async () => {
    mockFetch({ 'GET /config': () => json({ ...config, openai_configured: false }) });
    renderWithProviders(<ChatPage />);
    await waitFor(() => expect(screen.getByLabelText('Ask a question about your documents')).toBeDisabled());
  });

  it('clears the conversation', async () => {
    mockFetch({
      'GET /config': () => json(config),
      'POST /chat/stream': () => sseResponse(streamFrames()),
    });
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    await user.type(screen.getByLabelText('Ask a question about your documents'), 'hello{Enter}');
    await waitFor(() => expect(screen.getByTestId('assistant-message')).toHaveTextContent('800 characters'));
    await user.click(screen.getByRole('button', { name: /Clear conversation/ }));
    expect(screen.getByText('Start a conversation')).toBeInTheDocument();
    expect(within(document.body).queryByTestId('assistant-message')).toBeNull();
  });
});
