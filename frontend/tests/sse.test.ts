import { describe, expect, it } from 'vitest';
import { SSEParser, type SSEMessage } from '../src/utils/sse';

function collect() {
  const out: SSEMessage[] = [];
  const parser = new SSEParser((m) => out.push(m));
  return { out, parser };
}

describe('SSEParser', () => {
  it('parses complete frames', () => {
    const { out, parser } = collect();
    parser.feed('event: token\ndata: {"text":"Hi"}\n\nevent: done\ndata: {}\n\n');
    expect(out).toEqual([
      { event: 'token', data: '{"text":"Hi"}', id: undefined },
      { event: 'done', data: '{}', id: undefined },
    ]);
  });

  it('reassembles frames split at arbitrary byte boundaries', () => {
    const { out, parser } = collect();
    const frame = 'event: token\ndata: {"text":"Hello world"}\n\n';
    for (const ch of frame) parser.feed(ch);
    expect(out).toHaveLength(1);
    expect(JSON.parse(out[0].data)).toEqual({ text: 'Hello world' });
  });

  it('handles CRLF line endings split between chunks', () => {
    const { out, parser } = collect();
    parser.feed('event: a\r');
    parser.feed('\ndata: 1\r\n\r');
    parser.feed('\n');
    expect(out).toEqual([{ event: 'a', data: '1', id: undefined }]);
  });

  it('joins multi-line data and ignores comments', () => {
    const { out, parser } = collect();
    parser.feed(': keep-alive\nevent: msg\ndata: line1\ndata: line2\nid: 7\n\n');
    expect(out).toEqual([{ event: 'msg', data: 'line1\nline2', id: '7' }]);
  });

  it('defaults event name to "message" and skips frames without data', () => {
    const { out, parser } = collect();
    parser.feed('event: empty\n\ndata: x\n\n');
    expect(out).toEqual([{ event: 'message', data: 'x', id: undefined }]);
  });

  it('flushes an unterminated final event', () => {
    const { out, parser } = collect();
    parser.feed('event: done\ndata: {}');
    expect(out).toHaveLength(0);
    parser.flush();
    expect(out).toEqual([{ event: 'done', data: '{}', id: undefined }]);
  });
});
