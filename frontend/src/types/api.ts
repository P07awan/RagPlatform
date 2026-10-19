// Types mirroring the backend Pydantic schemas (backend/app/schemas).

export type DocumentStatus = 'pending' | 'processing' | 'indexed' | 'failed';

export interface DocumentOut {
  document_id: string;
  filename: string;
  file_type: string;
  size_bytes: number;
  content_hash: string;
  status: DocumentStatus;
  error: string | null;
  chunk_count: number;
  page_count: number | null;
  embedding_model: string | null;
  created_at: string;
  updated_at: string;
  indexed_at: string | null;
}

export interface DocumentList {
  items: DocumentOut[];
  total: number;
  limit: number;
  offset: number;
}

export type UploadOutcome = 'accepted' | 'indexed' | 'duplicate' | 'rejected' | 'failed';

export interface FileUploadResult {
  filename: string;
  outcome: UploadOutcome;
  document_id: string | null;
  message: string | null;
  document: DocumentOut | null;
}

export interface UploadResponse {
  results: FileUploadResult[];
  accepted: number;
  rejected: number;
}

export interface Citation {
  index: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  page_number: number | null;
  chunk_index: number;
  excerpt: string;
  score: number | null;
}

export interface RetrievedChunk {
  chunk_id: string;
  document_id: string;
  filename: string;
  chunk_index: number;
  page_number: number | null;
  content: string;
  dense_score: number | null;
  dense_rank: number | null;
  bm25_score: number | null;
  bm25_rank: number | null;
  fused_score: number | null;
  rerank_score: number | null;
}

export interface LatencyBreakdown {
  retrieval_ms: number | null;
  rerank_ms: number | null;
  generation_ms: number | null;
  total_ms: number | null;
}

export interface RetrievalMetadata {
  dense_candidates: number;
  bm25_candidates: number;
  fused_candidates: number;
  reranked: boolean;
  rerank_mode: string;
  chunks: RetrievedChunk[];
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  session_id: string;
  request_id: string | null;
  insufficient_context: boolean;
  cache_hit: boolean;
  model: string;
  latency: LatencyBreakdown;
  retrieval: RetrievalMetadata | null;
}

export interface ChatRequest {
  question: string;
  session_id?: string;
  document_ids?: string[];
  include_retrieval?: boolean;
}

export interface SearchResponse {
  query: string;
  dense_candidates: number;
  bm25_candidates: number;
  fused: RetrievedChunk[];
  reranked: RetrievedChunk[];
  rerank_applied: boolean;
  rerank_mode: string;
  latency_ms: Record<string, number>;
}

export type EvaluationStatus = 'queued' | 'running' | 'completed' | 'failed' | 'interrupted';

export interface EvaluationRun {
  evaluation_id: string;
  dataset: string;
  status: EvaluationStatus;
  total_cases: number;
  completed_cases: number;
  failed_cases: number;
  metrics: Record<string, number | null>;
  config: Record<string, unknown>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
}

export interface EvaluationList {
  items: EvaluationRun[];
  total: number;
  limit: number;
  offset: number;
}

export interface EvaluationCaseResult {
  case_index: number;
  case_id: string | null;
  question: string;
  reference_answer: string | null;
  generated_answer: string | null;
  retrieved_contexts: string[];
  reference_contexts: string[];
  scores: Record<string, number | null>;
  error: string | null;
  latency_ms: number | null;
}

export interface EvaluationResults {
  evaluation_id: string;
  items: EvaluationCaseResult[];
}

export interface DatasetInfo {
  name: string;
  cases: number;
  description: string | null;
}

export interface EvaluationPrerequisites {
  ready: boolean;
  missing: string[];
  available_metrics: string[];
  ragas_version: string | null;
}

export type ComponentState = 'ok' | 'degraded' | 'down' | 'disabled' | 'not_configured' | 'unknown';

export interface ComponentStatus {
  status: ComponentState;
  detail: string | null;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  environment: string;
  components: Record<string, ComponentStatus>;
}

export interface ConfigStatus {
  environment: string;
  llm_model: string;
  embedding_model: string;
  vector_size: number;
  collection: string;
  chunk_size: number;
  chunk_overlap: number;
  retrieval_top_k: number;
  rerank_top_k: number;
  rrf_k: number;
  reranker_enabled: boolean;
  reranker_model: string;
  reranker_fallback: string;
  reranker_state: string;
  cache_enabled: boolean;
  tracing_enabled: boolean;
  langsmith_project: string | null;
  auth_enabled: boolean;
  openai_configured: boolean;
  max_upload_size_mb: number;
  allowed_extensions: string[];
  warnings: string[];
}

export interface RecentChat {
  id: number;
  created_at: string;
  session_id: string | null;
  question_preview: string | null;
  latency_ms: number | null;
  citation_count: number | null;
  cache_hit: boolean;
  insufficient_context: boolean;
  status: string | null;
}

export interface DashboardStats {
  documents_total: number;
  documents_by_status: Record<string, number>;
  chunks_indexed: number | null;
  recent_documents: DocumentOut[];
  recent_chats: RecentChat[];
  last_evaluation: EvaluationRun | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string; request_id?: string | null; details?: unknown };
}
