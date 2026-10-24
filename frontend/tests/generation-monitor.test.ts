import test from 'node:test';
import assert from 'node:assert/strict';
import { createGenerationMonitor, type GenerationJob } from '../src/lib/studio/generation-monitor.ts';

class Socket {
 readyState = 1;
 onopen: (() => void) | null = null;
 onmessage: ((event: { data: string }) => void) | null = null;
 onerror: (() => void) | null = null;
 onclose: (() => void) | null = null;
 sent: string[] = [];
 close() { this.readyState = 3; }
 send(value: string) { this.sent.push(value); }
 snapshot(jobs: GenerationJob[], sequence = 1) { this.onmessage?.({ data: JSON.stringify({ type: 'snapshot', sequence, jobs }) }); }
}
const job = (status: GenerationJob['status'], when = 1): GenerationJob => ({ id: 'one', batch_id: 'batch', content_id: 'content', language: 'ko', status, message: status, result_ids: status === 'completed' ? ['result'] : [], created_at: '2026-10-19T00:00:00Z', updated_at: `2026-10-19T00:00:0${when}Z` });
const flush = () => new Promise(resolve => setImmediate(resolve));
function fixture(cursor: [string, GenerationJob['status']][] = []) {
 const sockets: Socket[] = [];
 let requests = 0, visible = true;
 let visibility = () => {};
 let resolveFetch: ((jobs: GenerationJob[]) => void) | undefined;
 const monitor = createGenerationMonitor({
  socket: () => { const socket = new Socket(); sockets.push(socket); return socket as unknown as WebSocket; },
  fetch: async () => { requests++; return new Promise(resolve => { resolveFetch = resolve; }); },
  visible: () => visible,
  onVisibility: callback => { visibility = callback; return () => { visibility = () => {}; }; },
  loadCursor: () => cursor,
  saveCursor: value => { cursor = value; },
 });
 return { monitor, sockets, get requests() { return requests; }, get cursor() { return cursor; }, hide() { visible = false; visibility(); }, show() { visible = true; visibility(); }, resolve(jobs: GenerationJob[]) { resolveFetch?.(jobs); } };
}

test('two subscribers share one socket and idle streaming makes no HTTP requests', async () => {
 const f = fixture(); const a = f.monitor.subscribe(() => {}); const b = f.monitor.subscribe(() => {});
 try {
  assert.equal(f.sockets.length, 1);
  f.sockets[0].snapshot([]);
  f.monitor.sync();
  assert.equal(f.requests, 0);
  assert.deepEqual(f.sockets[0].sent, ['resync']);
  a(); assert.equal(f.sockets[0].readyState, 1);
 } finally { b(); a(); }
 assert.equal(f.sockets[0].readyState, 3);
});

test('completion is deduplicated, reconnect history is restored and late acceptance cannot regress it', () => {
 const f = fixture([['one', 'running']]); const stop = f.monitor.subscribe(() => {});
 try {
  f.sockets[0].snapshot([job('completed', 3)]);
  assert.equal(f.monitor.state.finished.length, 1);
  f.sockets[0].snapshot([job('completed', 3)], 2);
  f.monitor.accept([job('queued', 1)]);
  assert.equal(f.monitor.state.finished.length, 1);
  assert.equal(f.monitor.state.jobs[0].status, 'completed');
  f.sockets[0].snapshot([job('running', 2)], 1);
  assert.equal(f.monitor.state.jobs[0].status, 'completed');
  f.monitor.dismiss('one');
  f.sockets[0].snapshot([job('completed', 3)], 3);
  assert.equal(f.monitor.state.finished.length, 0);
 } finally { stop(); }
});

test('accepting a job before the first snapshot never re-announces unrelated old results', () => {
 const f = fixture(); const stop = f.monitor.subscribe(() => {});
 try {
  f.monitor.accept([job('queued', 1)]);
  f.sockets[0].snapshot([{ ...job('completed', 3), id: 'historical' }, job('completed', 3)]);
  assert.deepEqual(f.monitor.state.finished.map(j => j.id), ['one']);
 } finally { stop(); }
});

test('opening an old completed history does not send a new completion notification', () => {
 const f = fixture(); const stop = f.monitor.subscribe(() => {});
 try {
  f.sockets[0].snapshot([job('completed', 3)]);
  assert.equal(f.monitor.state.finished.length, 0);
 } finally { stop(); }
});

test('a healthy stream overrides an older fallback response and hidden tabs stop HTTP fallback', async () => {
 const f = fixture(); const stop = f.monitor.subscribe(() => {});
 try {
  f.sockets[0].snapshot([job('running', 2)]);
  f.sockets[0].onerror?.();
  assert.equal(f.requests, 1);
  f.monitor.sync();
  const current = f.sockets[1];
  current.snapshot([job('completed', 3)]);
  f.resolve([job('queued', 1)]); await flush();
  assert.equal(f.monitor.state.connection, 'live');
  assert.equal(f.monitor.state.jobs[0].status, 'completed');
  f.hide(); current.onerror?.();
  assert.equal(f.requests, 1);
 } finally { stop(); }
});

test('a failed resync send preserves successful HTTP acceptance and reconnects safely', () => {
 const f = fixture(); const stop = f.monitor.subscribe(() => {});
 try {
  f.sockets[0].snapshot([]);
  f.sockets[0].send = () => { throw new Error('Transport closed during send'); };
  assert.doesNotThrow(() => f.monitor.accept([job('queued', 1)]));
  assert.equal(f.monitor.state.jobs[0].status, 'queued');
  assert.equal(f.monitor.state.connection, 'fallback');
  assert.equal(f.sockets[0].readyState, 3);
  assert.equal(f.requests, 1);
  assert.equal(f.monitor.state.finished.length, 0);
 } finally { stop(); }
});

test('shutdown ignores delayed responses and closes the transport without touching jobs', async () => {
 const f = fixture(); const stop = f.monitor.subscribe(() => {});
 f.sockets[0].snapshot([job('running', 2)]);
 f.sockets[0].onerror?.(); stop();
 f.resolve([job('completed', 3)]); await flush();
 assert.equal(f.monitor.state.jobs[0].status, 'running');
 assert.equal(f.monitor.state.finished.length, 0);
});
