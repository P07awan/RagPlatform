import type { ApiErrorBody } from '../types/api';

const DEFAULT_BASE_URL = 'http://localhost:8000/api/v1';

export const API_BASE_URL: string = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || DEFAULT_BASE_URL
).replace(/\/+$/, '');

const API_KEY_STORAGE = 'rag.apiKey';

/**
 * The application API key is entered by the user at runtime (Settings page) and kept in
 * this browser's localStorage. It is never baked into the JS bundle. This suits the
 * single-user portfolio deployment; a multi-user deployment needs real user auth.
 */
export function getApiKey(): string | null {
  try {
    return localStorage.getItem(API_KEY_STORAGE);
  } catch {
    return null;
  }
}

export function setApiKey(key: string | null): void {
  try {
    if (key) localStorage.setItem(API_KEY_STORAGE, key);
    else localStorage.removeItem(API_KEY_STORAGE);
  } catch {
    /* storage unavailable (private mode) – key just won't persist */
  }
  window.dispatchEvent(new Event('rag:api-key-changed'));
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, requestId: string | null = null, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }

  get isAuthError(): boolean {
    return this.status === 401 || this.status === 403;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

export function buildUrl(path: string, query?: Record<string, string | number | boolean | undefined | null>): string {
  const url = `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export function authHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  const key = getApiKey();
  if (key) headers.set('X-API-Key', key);
  return headers;
}

export async function toApiError(response: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | null = null;
  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    /* non-JSON error body */
  }
  const err = body?.error;
  const fallback =
    response.status === 401
      ? 'Authentication required: set the API key on the Settings page.'
      : `Request failed with HTTP ${response.status}`;
  return new ApiError(
    response.status,
    err?.code ?? 'http_error',
    err?.message ?? fallback,
    err?.request_id ?? response.headers.get('x-request-id'),
    err?.details,
  );
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, signal } = options;
  const headers = authHeaders({ Accept: 'application/json' });
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers.set('Content-Type', 'application/json');
    payload = JSON.stringify(body);
  }
  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), { method, headers, body: payload, signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, 'network_error', `Cannot reach the backend at ${API_BASE_URL}. Is it running?`);
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
