import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';
import { EvaluationsPage } from '../src/pages/EvaluationsPage';
import { SettingsPage } from '../src/pages/SettingsPage';
import type { EvaluationRun } from '../src/types/api';
import { config, health, json, mockFetch, renderWithProviders } from './utils';

const run: EvaluationRun = {
  evaluation_id: 'eval1234567890ab',
  dataset: 'sample_dataset',
  status: 'completed',
  total_cases: 2,
  completed_cases: 1,
  failed_cases: 1,
  metrics: { faithfulness: 0.875, answer_relevancy: 0.71 },
  config: {},
  error: null,
  created_at: '2026-10-01T10:00:00Z',
  started_at: '2026-10-01T10:00:00Z',
  finished_at: '2026-10-01T10:01:00Z',
  duration_seconds: 60.4,
};

const evalRoutes = (over: Record<string, () => Response> = {}) => ({
  'GET /evaluations': () => json({ items: [], total: 0, limit: 50, offset: 0 }),
  'GET /evaluations/datasets': () => json([{ name: 'sample_dataset', cases: 35, description: null }]),
  'GET /evaluations/prerequisites': () =>
    json({ ready: true, missing: [], available_metrics: ['faithfulness', 'answer_relevancy'], ragas_version: '0.4.3' }),
  ...over,
});

function renderEval(route = '/evaluations') {
  return renderWithProviders(
    <Routes>
      <Route path="/evaluations" element={<EvaluationsPage />} />
      <Route path="/evaluations/:evaluationId" element={<EvaluationsPage />} />
    </Routes>,
    { route },
  );
}

describe('EvaluationsPage', () => {
  it('shows an empty state without fabricated metrics', async () => {
    mockFetch(evalRoutes());
    renderEval();
    expect(await screen.findByText('No evaluation runs yet')).toBeInTheDocument();
    expect(screen.queryByText(/Faithfulness/)).toBeNull();
    expect(await screen.findByRole('button', { name: /Run evaluation/ })).toBeEnabled();
  });

  it('disables running and explains missing prerequisites', async () => {
    mockFetch(
      evalRoutes({
        'GET /evaluations/prerequisites': () =>
          json({ ready: false, missing: ['OPENAI_API_KEY is not configured (needed for answers and LLM-judged metrics).'], available_metrics: [], ragas_version: '0.4.3' }),
      }),
    );
    renderEval();
    expect(await screen.findByText(/OPENAI_API_KEY is not configured/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Run evaluation/ })).toBeDisabled();
  });

  it('renders real results: metrics, per-question rows and failures', async () => {
    mockFetch(
      evalRoutes({
        'GET /evaluations': () => json({ items: [run], total: 1, limit: 50, offset: 0 }),
        [`GET /evaluations/${run.evaluation_id}`]: () => json(run),
        [`GET /evaluations/${run.evaluation_id}/results`]: () =>
          json({
            evaluation_id: run.evaluation_id,
            items: [
              {
                case_index: 0, case_id: 'chk-01', question: 'What is the default chunk size?',
                reference_answer: '800 characters', generated_answer: 'It is 800 characters [1].',
                retrieved_contexts: ['The default chunk size is 800 characters'], reference_contexts: [],
                scores: { faithfulness: 0.875, answer_relevancy: 0.71 }, error: null, latency_ms: 1500,
              },
              {
                case_index: 1, case_id: 'x', question: 'Broken case question?', reference_answer: null, generated_answer: null,
                retrieved_contexts: [], reference_contexts: [], scores: {}, error: 'upstream_timeout: OpenAI request timed out', latency_ms: 60000,
              },
            ],
          }),
      }),
    );
    const user = userEvent.setup();
    renderEval(`/evaluations/${run.evaluation_id}`);
    expect(await screen.findByText('0.875', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('What is the default chunk size?')).toBeInTheDocument();
    expect(screen.getByText('Broken case question?')).toBeInTheDocument();

    await user.click(screen.getByText('What is the default chunk size?'));
    expect(screen.getByText('800 characters')).toBeInTheDocument();
    expect(screen.getByText('It is 800 characters [1].')).toBeInTheDocument();

    await user.click(screen.getByLabelText('Failed only'));
    expect(screen.queryByText('What is the default chunk size?')).toBeNull();
    expect(screen.getByText('Broken case question?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /JSON/ })).toBeEnabled();
    expect(screen.getByRole('button', { name: /CSV/ })).toBeEnabled();
  });
});

describe('SettingsPage', () => {
  it('shows configuration status without secrets and manages the API key locally', async () => {
    mockFetch({ 'GET /health': () => json(health), 'GET /config': () => json({ ...config, auth_enabled: true }) });
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />);
    expect(await screen.findByText('gpt-4o-mini')).toBeInTheDocument();
    expect(screen.getByText('text-embedding-3-small (1536d)')).toBeInTheDocument();
    expect(screen.getByText('cross-encoder/ms-marco-MiniLM-L-6-v2')).toBeInTheDocument();
    expect(screen.getByText('10 / 4')).toBeInTheDocument();
    expect(screen.getByText('No key set')).toBeInTheDocument();

    await user.type(screen.getByLabelText('API key'), 'my-secret-app-key');
    await user.click(screen.getByRole('button', { name: 'Save key' }));
    expect(localStorage.getItem('rag.apiKey')).toBe('my-secret-app-key');
    expect(await screen.findByText(/Key set \(••••-key\)/)).toBeInTheDocument();
    expect(screen.queryByText('my-secret-app-key')).toBeNull();
  });
});
