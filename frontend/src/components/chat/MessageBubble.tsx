import clsx from 'clsx';
import { AlertCircle, RotateCcw, Sparkles, User } from 'lucide-react';
import { memo, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage } from '../../hooks/useChatStream';
import { formatMs } from '../../utils/format';
import { Badge, Button } from '../ui';

// react-markdown does not render raw HTML (no rehype-raw), so model output cannot inject
// markup or scripts. Links are forced to open safely in a new tab.
const markdownComponents = {
  a: ({ href, children }: { href?: string; children?: ReactNode }) => {
    const safe = href && /^(https?:|mailto:)/i.test(href) ? href : undefined;
    return (
      <a href={safe} target="_blank" rel="noopener noreferrer nofollow">
        {children}
      </a>
    );
  },
  img: () => null, // never load remote images referenced by model output
};

function MessageBubbleImpl({
  message,
  selected,
  onSelect,
  onRetry,
  canRetry,
}: {
  message: ChatMessage;
  selected: boolean;
  onSelect: () => void;
  onRetry: () => void;
  canRetry: boolean;
}) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end gap-3">
        <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-brand-600 px-4 py-2.5 text-sm whitespace-pre-wrap text-white">{message.content}</div>
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 dark:bg-slate-800">
          <User className="h-4 w-4 text-slate-500" aria-hidden />
        </div>
      </div>
    );
  }

  const meta = message.metadata;
  const streaming = message.status === 'streaming';
  return (
    <div className="flex gap-3">
      <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-50 dark:bg-brand-500/10">
        <Sparkles className="h-4 w-4 text-brand-600" aria-hidden />
      </div>
      <div
        className={clsx(
          'max-w-[85%] min-w-0 flex-1 rounded-2xl rounded-tl-sm border bg-white px-4 py-3 text-sm shadow-sm dark:bg-slate-900',
          selected ? 'border-brand-500 ring-1 ring-brand-500/30' : 'border-slate-200 dark:border-slate-800',
        )}
      >
        {message.content ? (
          <div className={clsx('prose-answer', streaming && 'cursor-blink')} data-testid="assistant-message">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {message.content}
            </ReactMarkdown>
          </div>
        ) : streaming ? (
          <p className="flex items-center gap-2 text-slate-500">
            <span className="h-2 w-2 animate-pulse rounded-full bg-brand-500" /> Retrieving context…
          </p>
        ) : null}

        {message.status === 'error' && (
          <p role="alert" className="mt-2 flex items-start gap-2 text-red-600 dark:text-red-400">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            {message.error}
          </p>
        )}
        {message.status === 'cancelled' && <p className="mt-2 text-xs text-slate-500 italic">Generation cancelled.</p>}

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {meta?.insufficient_context && <Badge tone="yellow">Insufficient context</Badge>}
          {meta?.cache_hit && <Badge tone="blue">Cached</Badge>}
          {meta && <span>{formatMs(meta.latency.total_ms)}</span>}
          {meta && meta.retrieval && meta.retrieval.rerank_mode !== 'cross_encoder' && <Badge tone="yellow">rerank: {meta.retrieval.rerank_mode}</Badge>}
          {(message.citations?.length || message.chunks?.length) ? (
            <button onClick={onSelect} className="font-medium text-brand-600 hover:underline">
              {message.citations?.length ?? 0} citation{message.citations?.length === 1 ? '' : 's'} · view sources
            </button>
          ) : null}
          {(message.status === 'error' || message.status === 'cancelled') && (
            <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={onRetry} disabled={!canRetry}>
              <RotateCcw className="h-3 w-3" aria-hidden /> Retry
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export const MessageBubble = memo(MessageBubbleImpl);
