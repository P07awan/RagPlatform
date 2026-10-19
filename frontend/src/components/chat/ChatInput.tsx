import { SendHorizontal, Square } from 'lucide-react';
import { useState, type FormEvent, type KeyboardEvent } from 'react';
import { Button } from '../ui';

const MAX_CHARS = 2000;

export function ChatInput({
  onSend,
  onCancel,
  isStreaming,
  disabled,
  disabledReason,
}: {
  onSend: (q: string) => boolean;
  onCancel: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const [value, setValue] = useState('');
  const tooLong = value.length > MAX_CHARS;

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (isStreaming || disabled || tooLong) return;
    if (onSend(value)) setValue('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={submit} className="border-t border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-end gap-2">
        <label htmlFor="chat-input" className="sr-only">
          Ask a question about your documents
        </label>
        <textarea
          id="chat-input"
          rows={2}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={disabled ? (disabledReason ?? 'Chat unavailable') : 'Ask a question about your documents…'}
          disabled={disabled}
          className="max-h-40 min-h-[2.75rem] flex-1 resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none disabled:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:disabled:bg-slate-900"
        />
        {isStreaming ? (
          <Button variant="secondary" onClick={onCancel} aria-label="Stop generating">
            <Square className="h-4 w-4" aria-hidden /> Stop
          </Button>
        ) : (
          <Button type="submit" disabled={!value.trim() || disabled || tooLong} aria-label="Send question">
            <SendHorizontal className="h-4 w-4" aria-hidden /> Send
          </Button>
        )}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-slate-400">
        <span>Enter to send · Shift+Enter for a new line</span>
        <span className={tooLong ? 'text-red-500' : undefined}>
          {value.length}/{MAX_CHARS}
        </span>
      </div>
    </form>
  );
}
