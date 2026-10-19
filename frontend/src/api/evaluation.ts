import type {
  DatasetInfo,
  EvaluationList,
  EvaluationPrerequisites,
  EvaluationResults,
  EvaluationRun,
} from '../types/api';
import { apiRequest } from './client';

export const listEvaluations = (limit = 20, offset = 0) =>
  apiRequest<EvaluationList>('/evaluations', { query: { limit, offset } });

export const getEvaluation = (id: string) => apiRequest<EvaluationRun>(`/evaluations/${encodeURIComponent(id)}`);

export const getEvaluationResults = (id: string) =>
  apiRequest<EvaluationResults>(`/evaluations/${encodeURIComponent(id)}/results`);

export const listDatasets = () => apiRequest<DatasetInfo[]>('/evaluations/datasets');

export const getPrerequisites = () => apiRequest<EvaluationPrerequisites>('/evaluations/prerequisites');

export const runEvaluation = (body: { dataset: string; limit?: number }) =>
  apiRequest<EvaluationRun>('/evaluations/run', { method: 'POST', body });
