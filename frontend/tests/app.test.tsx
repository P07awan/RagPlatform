import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { App } from '../src/App';
import { config, emptyStats, health, json, mockFetch, renderWithProviders } from './utils';

// Pages are lazy-loaded chunks; allow time for the dynamic import under parallel test load.
const LAZY = { timeout: 8000 };

function defaultRoutes() {
  return {
    'GET /health': () => json(health),
    'GET /config': () => json(config),
    'GET /stats': () => json(emptyStats),
    'GET /documents': () => json({ items: [], total: 0, limit: 20, offset: 0 }),
    'GET /evaluations': () => json({ items: [], total: 0, limit: 50, offset: 0 }),
    'GET /evaluations/datasets': () => json([{ name: 'sample_dataset', cases: 35, description: null }]),
    'GET /evaluations/prerequisites': () => json({ ready: true, missing: [], available_metrics: ['faithfulness'], ragas_version: '0.4.3' }),
  };
}

describe('App shell', () => {
  it('renders the dashboard with real (empty) data states', async () => {
    mockFetch(defaultRoutes());
    renderWithProviders(<App />);
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(await screen.findByText('No documents yet')).toBeInTheDocument();
    expect(screen.getByText('No chat activity yet')).toBeInTheDocument();
    expect(screen.getByText('No evaluation runs')).toBeInTheDocument();
    expect((await screen.findAllByText('Backend healthy')).length).toBeGreaterThan(0);
  });

  it('navigates between pages via the sidebar', { timeout: 30000 }, async () => {
    mockFetch(defaultRoutes());
    const user = userEvent.setup();
    renderWithProviders(<App />);
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0];
    await user.click(within(nav).getByRole('link', { name: 'Documents' }));
    expect(await screen.findByRole('heading', { name: 'Documents' }, LAZY)).toBeInTheDocument();
    await user.click(within(nav).getByRole('link', { name: 'Chat' }));
    expect(await screen.findByRole('heading', { name: 'Chat' }, LAZY)).toBeInTheDocument();
    await user.click(within(nav).getByRole('link', { name: 'Evaluations' }));
    expect(await screen.findByRole('heading', { name: 'Evaluations' }, LAZY)).toBeInTheDocument();
    await user.click(within(nav).getByRole('link', { name: 'Settings' }));
    expect(await screen.findByRole('heading', { name: 'Settings' }, LAZY)).toBeInTheDocument();
  });

  it('shows the 404 page for unknown routes', async () => {
    mockFetch(defaultRoutes());
    renderWithProviders(<App />, { route: '/does-not-exist' });
    expect(await screen.findByText('Page not found')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to dashboard' })).toHaveAttribute('href', '/');
  });

  it('shows configuration warnings from the backend', async () => {
    mockFetch({ ...defaultRoutes(), 'GET /config': () => json({ ...config, warnings: ['API_KEY is not set'] }) });
    renderWithProviders(<App />);
    expect(await screen.findByText('API_KEY is not set')).toBeInTheDocument();
  });

  it('reports an unreachable backend', async () => {
    mockFetch({});
    const fetchFn = globalThis.fetch as unknown as { mockImplementation: (f: () => never) => void };
    fetchFn.mockImplementation(() => {
      throw new TypeError('Failed to fetch');
    });
    renderWithProviders(<App />);
    expect((await screen.findAllByText('Backend unreachable')).length).toBeGreaterThan(0);
  });
});
