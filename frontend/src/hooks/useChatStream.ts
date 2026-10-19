import { useCallback, useEffect, useRef, useState } from 'react';
import { streamChat } from '../api/chat';
import { ApiError } from '../api/client';
import type { ChatResponse, Citation, RetrievedChunk } from '../types/api';

export type MessageStatus = 'streaming' | 'done' | 'error' | 'cancelled';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  status: MessageStatus;
  question?: string; // for assistant messages: the question that produced it (used by retry)
  citations?: Citation[];
  chunks?: RetrievedChunk[];
  metadata?: ChatResponse;
  error?: string;
}

const SESSION_KEY = 'rag.chat.session';
const MESSAGES_KEY = 'rag.chat.messages';

function newId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().replace(/-/g, '')
    : Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function loadMessages(): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(MESSAGES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatMessage[];
    // A reload mid-stream leaves a message 'streaming' forever – mark it interrupted.
    return parsed.map((m) => (m.status === 'streaming' ? { ...m, status: 'error', error: 'Interrupted by page reload' } : m));
  } catch {
    return [];
  }
}

function loadSession(): string {
  try {
    const existing = sessionStorage.getItem(SESSION_KEY);
    if (existing) return existing;
    const id = newId();
    sessionStorage.setItem(SESSION_KEY, id);
    return id;
  } catch {
    return newId();
  }
}

export function useChatStream() {
  const [messages, setMessages] = useState<ChatMessage[]>(loadMessages);
  const [sessionId, setSessionId] = useState<string>(loadSession);
  const [isStreaming, setIsStreaming] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false); // synchronous guard against double submits

  useEffect(() => {
    try {
      sessionStorage.setItem(MESSAGES_KEY, JSON.stringify(messages.slice(-50)));
    } catch {
      /* ignore quota / unavailable storage */
    }
  }, [messages]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const patch = useCallback((id: string, update: (m: ChatMessage) => ChatMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? update(m) : m)));
  }, []);

  const runStream = useCallback(
    async (question: string, assistantId: string) => {
      const controller = new AbortController();
      controllerRef.current = controller;
      busyRef.current = true;
      setIsStreaming(true);
      try {
        await streamChat(
          { question, session_id: sessionId, include_retrieval: true },
          {
            onSources: ({ chunks }) => patch(assistantId, (m) => ({ ...m, chunks })),
            onToken: (text) => patch(assistantId, (m) => ({ ...m, content: m.content + text })),
            onMetadata: (meta) =>
              patch(assistantId, (m) => ({
                ...m,
                // The server-validated answer replaces the streamed text (invalid citation markers removed).
                content: meta.answer,
                citations: meta.citations,
                chunks: meta.retrieval?.chunks?.length ? meta.retrieval.chunks : m.chunks,
                metadata: meta,
              })),
            onError: (err) => patch(assistantId, (m) => ({ ...m, status: 'error', error: err.message })),
            onDone: () => patch(assistantId, (m) => (m.status === 'streaming' ? { ...m, status: 'done' } : m)),
          },
          controller.signal,
        );
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') {
          patch(assistantId, (m) => ({ ...m, status: 'cancelled' }));
        } else {
          const message = e instanceof ApiError ? e.message : 'Unexpected error while streaming';
          patch(assistantId, (m) => ({ ...m, status: 'error', error: message }));
        }
      } finally {
        busyRef.current = false;
        controllerRef.current = null;
        setIsStreaming(false);
      }
    },
    [patch, sessionId],
  );

  const send = useCallback(
    (question: string) => {
      const q = question.trim();
      if (!q || busyRef.current) return false;
      const assistantId = newId();
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: 'user', content: q, status: 'done' },
        { id: assistantId, role: 'assistant', content: '', status: 'streaming', question: q },
      ]);
      void runStream(q, assistantId);
      return true;
    },
    [runStream],
  );

  const retry = useCallback(
    (assistantId: string) => {
      if (busyRef.current) return;
      const msg = messages.find((m) => m.id === assistantId);
      if (!msg?.question) return;
      patch(assistantId, (m) => ({ ...m, content: '', status: 'streaming', error: undefined, citations: undefined, chunks: undefined, metadata: undefined }));
      void runStream(msg.question, assistantId);
    },
    [messages, patch, runStream],
  );

  const cancel = useCallback(() => controllerRef.current?.abort(), []);

  const clear = useCallback(() => {
    controllerRef.current?.abort();
    setMessages([]);
    const id = newId();
    setSessionId(id);
    try {
      sessionStorage.setItem(SESSION_KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  return { messages, sessionId, isStreaming, send, retry, cancel, clear };
}
