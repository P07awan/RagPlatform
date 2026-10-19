// Incremental Server-Sent Events parser (WHATWG event-stream format).
// Handles frames split across network chunks, CRLF/LF/CR line endings,
// multi-line `data:` fields and `:` comment lines.

export interface SSEMessage {
  event: string;
  data: string;
  id?: string;
}

export class SSEParser {
  private buffer = '';
  private eventName = '';
  private dataLines: string[] = [];
  private lastId: string | undefined;
  private readonly onMessage: (msg: SSEMessage) => void;

  constructor(onMessage: (msg: SSEMessage) => void) {
    this.onMessage = onMessage;
  }

  feed(chunk: string): void {
    this.buffer += chunk;
    // Normalise line endings; keep a trailing lone '\r' until we know if '\n' follows.
    let text = this.buffer;
    const endsWithCR = text.endsWith('\r');
    if (endsWithCR) text = text.slice(0, -1);
    text = text.replace(/\r\n?/g, '\n');
    const lines = text.split('\n');
    // Last element is an incomplete line (possibly empty) – keep it buffered.
    this.buffer = (lines.pop() ?? '') + (endsWithCR ? '\r' : '');
    for (const line of lines) this.processLine(line);
  }

  /** Dispatch any complete-but-unterminated event at end of stream. */
  flush(): void {
    if (this.buffer) {
      this.processLine(this.buffer.replace(/\r$/, ''));
      this.buffer = '';
    }
    this.dispatch();
  }

  private processLine(line: string): void {
    if (line === '') {
      this.dispatch();
      return;
    }
    if (line.startsWith(':')) return; // comment / keep-alive
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    switch (field) {
      case 'event':
        this.eventName = value;
        break;
      case 'data':
        this.dataLines.push(value);
        break;
      case 'id':
        this.lastId = value;
        break;
      default:
        break; // 'retry' and unknown fields are ignored
    }
  }

  private dispatch(): void {
    if (this.dataLines.length === 0) {
      this.eventName = '';
      return;
    }
    this.onMessage({
      event: this.eventName || 'message',
      data: this.dataLines.join('\n'),
      id: this.lastId,
    });
    this.eventName = '';
    this.dataLines = [];
  }
}
