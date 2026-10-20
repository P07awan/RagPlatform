import { describe, expect, it } from 'vitest';
import { buildUrl, normalizeBaseUrl } from '../src/api/client';

describe('normalizeBaseUrl', () => {
  it('keeps a full API base URL unchanged', () => {
    expect(normalizeBaseUrl('https://ragplatform.onrender.com/api/v1')).toBe('https://ragplatform.onrender.com/api/v1');
  });
  it('strips trailing slashes and whitespace', () => {
    expect(normalizeBaseUrl('  https://ragplatform.onrender.com/api/v1/// ')).toBe('https://ragplatform.onrender.com/api/v1');
  });
  it('adds /api/v1 when only an origin is configured', () => {
    expect(normalizeBaseUrl('https://ragplatform.onrender.com')).toBe('https://ragplatform.onrender.com/api/v1');
    expect(normalizeBaseUrl('https://ragplatform.onrender.com/')).toBe('https://ragplatform.onrender.com/api/v1');
  });
  it('does not duplicate the prefix', () => {
    expect(normalizeBaseUrl('http://localhost:8000/api/v1/')).toBe('http://localhost:8000/api/v1');
  });
});

describe('buildUrl', () => {
  it('joins paths with exactly one slash', () => {
    expect(buildUrl('/health')).toMatch(/[^/]\/api\/v1\/health$/);
    expect(buildUrl('health')).toMatch(/[^/]\/api\/v1\/health$/);
  });
});
