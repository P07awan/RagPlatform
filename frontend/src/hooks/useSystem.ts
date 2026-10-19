import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useState } from 'react';
import { getApiKey } from '../api/client';
import { getConfig, getHealth, getStats } from '../api/health';

export const queryKeys = {
  health: ['health'] as const,
  config: ['config'] as const,
  stats: ['stats'] as const,
  documents: (offset: number) => ['documents', offset] as const,
  evaluations: ['evaluations'] as const,
  evaluation: (id: string) => ['evaluation', id] as const,
  evaluationResults: (id: string) => ['evaluation', id, 'results'] as const,
  datasets: ['datasets'] as const,
  prerequisites: ['evaluation-prerequisites'] as const,
};

export function useHealth() {
  return useQuery({ queryKey: queryKeys.health, queryFn: getHealth, refetchInterval: 30_000, retry: 0 });
}

export function useConfig() {
  return useQuery({ queryKey: queryKeys.config, queryFn: getConfig, staleTime: 60_000 });
}

export function useStats() {
  return useQuery({ queryKey: queryKeys.stats, queryFn: getStats, refetchInterval: 15_000 });
}

export function useApiKeyState() {
  const [key, setKey] = useState<string | null>(getApiKey);
  useEffect(() => {
    const onChange = () => setKey(getApiKey());
    window.addEventListener('rag:api-key-changed', onChange);
    window.addEventListener('storage', onChange);
    return () => {
      window.removeEventListener('rag:api-key-changed', onChange);
      window.removeEventListener('storage', onChange);
    };
  }, []);
  return key;
}

export type Theme = 'light' | 'dark';

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() =>
    document.documentElement.classList.contains('dark') ? 'dark' : 'light',
  );
  const setTheme = useCallback((t: Theme) => {
    document.documentElement.classList.toggle('dark', t === 'dark');
    try {
      localStorage.setItem('rag.theme', t);
    } catch {
      /* ignore */
    }
    setThemeState(t);
  }, []);
  const toggle = useCallback(() => setTheme(theme === 'dark' ? 'light' : 'dark'), [setTheme, theme]);
  return { theme, toggle };
}
