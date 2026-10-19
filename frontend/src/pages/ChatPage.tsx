import { MessageSquare, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ChatInput } from '../components/chat/ChatInput';
import { MessageBubble } from '../components/chat/MessageBubble';
import { SourcesPanel } from '../components/chat/SourcesPanel';
import { PageHeader } from '../components/layout/PageHeader';
import { Button, Card, CardHeader, EmptyState } from '../components/ui';
import { useChatStream } from '../hooks/useChatStream';
import { useConfig } from '../hooks/useSystem';

export function ChatPage() {
  const { messages, sessionId, isStreaming, send, retry, cancel, clear } = useChatStream();
  const config = useConfig();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Follow the newest assistant message unless the user picked another one.
  const lastAssistant = useMemo(() => [...messages].reverse().find((m) => m.role === 'assistant') ?? null, [messages]);
  const selected = messages.find((m) => m.id === selectedId) ?? lastAssistant;

  const lastContentLength = messages.at(-1)?.content.length ?? 0;
  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' });
  }, [messages.length, lastContentLength]);

  const openaiMissing = config.data ? !config.data.openai_configured : false;

  const handleSend = (q: string) => {
    const ok = send(q);
    if (ok) setSelectedId(null);
    return ok;
  };

  return (
    <>
      <PageHeader
        title="Chat"
        description="Ask questions answered strictly from your indexed documents, with citations."
        actions={
          <Button variant="secondary" onClick={() => { clear(); setSelectedId(null); }} disabled={messages.length === 0 && !isStreaming}>
            <Trash2 className="h-4 w-4" aria-hidden /> Clear conversation
          </Button>
        }
      />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Card className="flex h-[calc(100vh-13rem)] min-h-[420px] flex-col overflow-hidden">
          <div className="flex-1 space-y-5 overflow-y-auto p-4" aria-live="polite">
            {messages.length === 0 ? (
              <EmptyState
                icon={<MessageSquare className="h-6 w-6" />}
                title="Start a conversation"
                description="Answers are grounded in the documents you upload. If the documents don't contain the answer, the assistant will say so."
              />
            ) : (
              messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  selected={selected?.id === m.id && m.role === 'assistant'}
                  onSelect={() => setSelectedId(m.id)}
                  onRetry={() => retry(m.id)}
                  canRetry={!isStreaming}
                />
              ))
            )}
            <div ref={bottomRef} />
          </div>
          <ChatInput
            onSend={handleSend}
            onCancel={cancel}
            isStreaming={isStreaming}
            disabled={openaiMissing}
            disabledReason="OPENAI_API_KEY is not configured on the backend"
          />
        </Card>
        <Card className="h-fit max-h-[calc(100vh-13rem)] overflow-y-auto lg:sticky lg:top-20">
          <CardHeader title="Sources" description={<span className="font-mono">session {sessionId.slice(0, 8)}</span>} />
          <SourcesPanel message={selected} />
        </Card>
      </div>
    </>
  );
}
