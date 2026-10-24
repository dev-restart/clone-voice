import { t } from '../i18n/core.ts';
// Pure client controller: one connection shared by any number of UI subscribers.
// WebSocket delivery observes durable backend jobs; it never submits inference.
export type GenerationJob = {
 id: string; batch_id: string; content_id: string; language: string;
 status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
 message: string; result_ids: string[]; created_at: string; updated_at: string; parent_job_id?: string | null;
 progress?: { percent: number; message: string; timestamp: string };
};
export type GenerationLiveState = {
 jobs: GenerationJob[]; finished: GenerationJob[]; loaded: boolean;
 connection: 'connecting' | 'live' | 'fallback' | 'offline'; error: string;
};
export const initialGenerationState = (): GenerationLiveState => ({ jobs: [], finished: [], loaded: false, connection: 'connecting', error: '' });
export const isActiveGeneration = (job: GenerationJob) => job.status === 'queued' || job.status === 'running';
const isFinished = (job: GenerationJob) => job.status === 'completed' || job.status === 'failed';

type Environment = {
 socket: () => WebSocket;
 fetch: (signal: AbortSignal) => Promise<GenerationJob[]>;
 visible: () => boolean;
 onVisibility: (callback: () => void) => () => void;
 loadCursor?: () => [string, GenerationJob['status']][];
 saveCursor?: (cursor: [string, GenerationJob['status']][]) => void;
};
function validJobs(value: unknown): value is GenerationJob[] {
 return Array.isArray(value) && value.length <= 200 && value.every(j => j && typeof j.id === 'string' && typeof j.content_id === 'string' && typeof j.batch_id === 'string' && typeof j.language === 'string' && typeof j.updated_at === 'string' && typeof j.created_at === 'string' && typeof j.message === 'string' && ['queued', 'running', 'completed', 'failed', 'cancelled'].includes(j.status) && Array.isArray(j.result_ids));
}

export function createGenerationMonitor(env: Environment) {
 let state = initialGenerationState();
 const listeners = new Set<(value: GenerationLiveState) => void>();
 const known = new Map<string, GenerationJob['status']>();
 const acceptedAt = new Map<string, number>();
 let socket: WebSocket | null = null;
 let running = false, failures = 0, httpFailures = 0, revision = 0;
 let initialSnapshotReceived = false;
 let connectionEpoch = 0, sequence = 0, lastSync = 0;
 let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
 let fallbackTimer: ReturnType<typeof setTimeout> | undefined;
 let watchdog: ReturnType<typeof setTimeout> | undefined;
 let requestTimeout: ReturnType<typeof setTimeout> | undefined;
 let request: AbortController | null = null;
 let releaseVisibility: (() => void) | undefined;

 function isLive() { return state.connection === 'live'; }
 function emit() { for (const listener of listeners) listener(state); }
 function update(patch: Partial<GenerationLiveState>) { state = { ...state, ...patch }; emit(); }
 function apply(jobs: GenerationJob[], replace: boolean) {
  if (!validJobs(jobs)) throw new Error('Invalid job snapshot');
  const before = new Map(state.jobs.map(j => [j.id, j]));
  const next = replace ? new Map<string, GenerationJob>() : new Map(before);
  const justFinished: GenerationJob[] = [];
  for (const incoming of jobs) {
   const previous = before.get(incoming.id);
   // The POST acceptance can arrive after a faster completion event.
   const job = previous && previous.updated_at > incoming.updated_at ? previous : incoming;
   next.set(job.id, job);
   const old = known.get(job.id);
   if (isFinished(job) && old !== job.status && (old === 'queued' || old === 'running' || (old === undefined && initialSnapshotReceived))) justFinished.push(job);
   known.delete(job.id); known.set(job.id, job.status);
   if (replace) acceptedAt.delete(job.id);
  }
  if (replace) for (const [id, when] of acceptedAt) {
   if (Date.now() - when < 30_000 && before.has(id) && !next.has(id)) next.set(id, before.get(id)!);
   else acceptedAt.delete(id);
  }
  if (replace) initialSnapshotReceived = true;
  while (known.size > 300) known.delete(known.keys().next().value!);
  try { env.saveCursor?.([...known]); } catch { /* Memory-only recovery still works. */ }
  revision++;
  const finished = [...justFinished, ...state.finished.filter(j => !justFinished.some(n => n.id === j.id))].slice(0, 30);
  update({ jobs: [...next.values()].sort((a,b) => b.created_at.localeCompare(a.created_at)).slice(0, 132), finished, loaded: true });
 }
 function clearRequest() {
  request?.abort(); request = null;
  clearTimeout(requestTimeout); clearTimeout(fallbackTimer);
  requestTimeout = fallbackTimer = undefined;
 }
 function armWatchdog(ms: number, current: WebSocket) {
  clearTimeout(watchdog);
  watchdog = setTimeout(() => { if (socket === current) disconnect(current); }, ms);
 }
 function disconnect(current: WebSocket) {
  if (!running || socket !== current) return;
  current.onopen = null; current.onmessage = null; current.onerror = null; current.onclose = null;
  socket = null; clearTimeout(watchdog);
  try { current.close(); } catch { /* Already closed. */ }
  update({ connection: 'fallback', error: t('monitor.recovering') });
  const delay = Math.min(30_000, 1000 * 2 ** Math.min(failures++, 5));
  reconnectTimer = setTimeout(connect, env.visible() ? delay : 30_000);
  if (env.visible() && !fallbackTimer && !request) void fetchFallback();
 }
 function connect() {
  if (!running || socket) return;
  clearTimeout(reconnectTimer);
  const epoch = ++connectionEpoch;
  sequence = 0;
  let current: WebSocket;
  try { current = env.socket(); }
  catch {
   update({ connection: 'fallback', error: t('monitor.polling') });
   reconnectTimer = setTimeout(connect, 30_000);
   if (env.visible() && !request && !fallbackTimer) void fetchFallback();
   return;
  }
  socket = current;
  armWatchdog(10_000, current);
  current.onopen = () => { if (running && socket === current) armWatchdog(10_000, current); };
  current.onmessage = event => {
   if (!running || socket !== current || epoch !== connectionEpoch) return;
   try {
    const payload = JSON.parse(String(event.data));
    if (payload.type === 'heartbeat') { armWatchdog(45_000, current); return; }
    if (payload.type !== 'snapshot' || !Number.isSafeInteger(payload.sequence) || !validJobs(payload.jobs)) throw new Error('Invalid stream');
    if (payload.sequence <= sequence) return;
    sequence = payload.sequence;
    clearRequest(); failures = 0; httpFailures = 0;
    state = { ...state, connection: 'live', error: '' };
    apply(payload.jobs, true);
    armWatchdog(45_000, current);
   } catch { disconnect(current); }
  };
  current.onerror = () => disconnect(current);
  current.onclose = () => disconnect(current);
 }
 async function fetchFallback() {
  if (!running || request || !env.visible() || isLive()) return;
  clearTimeout(fallbackTimer); fallbackTimer = undefined;
  const controller = new AbortController(); request = controller;
  const beforeRevision = revision;
  requestTimeout = setTimeout(() => controller.abort(), 10_000);
  try {
   const jobs = await env.fetch(controller.signal);
   if (!running || request !== controller || controller.signal.aborted || isLive()) return;
   if (beforeRevision === revision) apply(jobs, true);
   httpFailures = 0;
   update({ connection: 'fallback', error: t('monitor.recoveringPoll') });
  } catch {
   if (running && request === controller) {
    httpFailures++;
    update({ connection: 'offline', error: t('monitor.offline') });
   }
  } finally {
   if (request === controller) {
    request = null; clearTimeout(requestTimeout);
    if (running && env.visible() && !isLive()) {
     const delay = httpFailures ? Math.min(60_000, 5000 * 2 ** Math.min(httpFailures, 4)) : state.jobs.some(isActiveGeneration) ? 5000 : 60_000;
     fallbackTimer = setTimeout(() => { fallbackTimer = undefined; void fetchFallback(); }, delay);
    }
   }
  }
 }
 function sync() {
  if (!running) return;
  if (socket?.readyState === 1 && state.connection === 'live') {
   if (Date.now() - lastSync >= 1000) {
    lastSync = Date.now();
    const current = socket;
    try { current.send('resync'); }
    catch {
     // The network can close after readyState was checked. A lost status
     // message must not make a successfully accepted generation look failed.
     disconnect(current);
    }
   }
  } else if (env.visible()) {
   if (!socket) { clearTimeout(reconnectTimer); connect(); }
   void fetchFallback();
  }
 }
 function start() {
  running = true;
  state = { ...state, connection: 'connecting', error: '' };
  try { for (const [id, status] of env.loadCursor?.() ?? []) if (typeof id === 'string' && ['queued','running','completed','failed','cancelled'].includes(status)) known.set(id, status); } catch { /* No durable cursor available. */ }
  releaseVisibility = env.onVisibility(() => {
   if (env.visible()) sync();
   else clearRequest(); // Keep the WebSocket alive for optional OS notifications.
  });
  connect();
 }
 function stop() {
  running = false; connectionEpoch++;
  clearTimeout(reconnectTimer); clearTimeout(fallbackTimer); clearTimeout(watchdog);
  reconnectTimer = fallbackTimer = watchdog = undefined;
  clearRequest(); releaseVisibility?.();
  if (socket) {
   const current = socket; socket = null;
   current.onopen = current.onmessage = current.onclose = current.onerror = null;
   current.close();
  }
 }
 return {
  subscribe(listener: (value: GenerationLiveState) => void) {
   listeners.add(listener); listener(state);
   if (listeners.size === 1) start();
   return () => { listeners.delete(listener); if (!listeners.size) stop(); };
  },
  sync,
  accept(jobs: GenerationJob[]) {
   if (!validJobs(jobs)) return;
   for (const job of jobs) acceptedAt.set(job.id, Date.now());
   apply(jobs, false);
   sync();
  },
  dismiss(id: string) { update({ finished: state.finished.filter(j => j.id !== id) }); },
  get state() { return state; },
 };
}
