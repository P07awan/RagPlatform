export type BadgeTone = 'green' | 'yellow' | 'red' | 'blue' | 'gray';

export function statusTone(status: string): BadgeTone {
  switch (status) {
    case 'ok':
    case 'indexed':
    case 'completed':
    case 'loaded':
      return 'green';
    case 'pending':
    case 'processing':
    case 'running':
    case 'queued':
      return 'blue';
    case 'degraded':
    case 'interrupted':
    case 'not_loaded':
    case 'not_configured':
      return 'yellow';
    case 'failed':
    case 'down':
      return 'red';
    default:
      return 'gray';
  }
}
