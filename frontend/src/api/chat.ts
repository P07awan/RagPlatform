import type { ChatRequest, ChatResponse, RetrievedChunk } from '../types/api';
import { SSEParser } from '../utils/sse';
import { ApiError, apiRequest, authHeaders, buildUrl, toApiError, API_BASE_URL } from './client';

export function sendChat(req: ChatRequest, signal?: AbortSignal): Promise<ChatResponse> {
  return apiRequest<ChatResponse>('/chat', { method: 'POST', body: req, signal });
}

export interface StreamHandlers {
  onStart?: (data: { request_id: string | null; session_id: string }) => void;
  onSources?: (data: { chunks: RetrievedChunk[]; rerank_mode: string | null; cache_hit: boolean }) => void;
  onToken?: (text: string) => void;
  onMetadata?: (data: ChatResponse) => void;
  onError?: (error: ApiError) => void;
  onDone?: () => void;
}

/**
 * POST /chat/stream and dispatch SSE events incrementally.
 * Resolves when the stream ends; rejects only on transport-level failures (abort excluded).
 * Event contract: start → sources → token* → metadata → done (error may replace metadata).
 */
export async function streamChat(req: ChatRequest, handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  let response: Response;
  try {
    response = await fetch(buildUrl('/chat/stream'), {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
      body: JSON.stringify(req),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, 'network_error', `Cannot reach the backend at ${API_BASE_URL}. Is it running?`);
  }
  if (!response.ok) throw await toApiError(response);
  if (!response.body) throw new ApiError(0, 'stream_unsupported', 'Streaming is not supported by this browser');

  let sawDone = false;
  const parser = new SSEParser(({ event, data }) => {
    let payload: unknown;
    try {
      payload = JSON.parse(data);
    } catch {
      return; // ignore malformed frames rather than crashing the UI
    }
    switch (event) {
      case 'start':
        handlers.onStart?.(payload as { request_id: string | null; session_id: string });
        break;
      case 'sources':
        handlers.onSources?.(payload as { chunks: RetrievedChunk[]; rerank_mode: string | null; cache_hit: boolean });
        break;
      case 'token':
        handlers.onToken?.((payload as { text: string }).text);
        break;
      case 'metadata':
        handlers.onMetadata?.(payload as ChatResponse);
        break;
      case 'error': {
        const p = payload as { code?: string; message?: string; request_id?: string | null };
        handlers.onError?.(new ApiError(500, p.code ?? 'stream_error', p.message ?? 'Streaming failed', p.request_id ?? null));
        break;
      }
      case 'done':
        sawDone = true;
        handlers.onDone?.();
        break;
      default:
        break;
    }
  });

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      if (value) parser.feed(value);
    }
    parser.flush();
  } finally {
    reader.releaseLock();
  }
  if (!sawDone) {
    handlers.onError?.(new ApiError(0, 'stream_interrupted', 'The response stream was interrupted before completion.'));
  }
}
