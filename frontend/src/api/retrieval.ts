import type { SearchResponse } from '../types/api';
import { apiRequest } from './client';

export interface SearchParams {
  query: string;
  top_k?: number;
  rerank_top_k?: number;
  rerank?: boolean;
  document_ids?: string[];
}

export const searchRetrieval = (body: SearchParams, signal?: AbortSignal) =>
  apiRequest<SearchResponse>('/retrieval/search', { method: 'POST', body, signal });
