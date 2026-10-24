import { readable } from 'svelte/store';
import { apiFetch, apiWebSocketUrl } from './api';
import { createGenerationMonitor, initialGenerationState, type GenerationJob } from './generation-monitor';
export { isActiveGeneration } from './generation-monitor';
export type { GenerationJob, GenerationLiveState } from './generation-monitor';

export async function fetchGenerationJobs(contentId?: string, signal?: AbortSignal): Promise<GenerationJob[]> {
 const response = await apiFetch('/api/generation-jobs' + (contentId ? '?content_id=' + encodeURIComponent(contentId) : ''), { signal });
 return (await response.json()).jobs ?? [];
}
let monitor: ReturnType<typeof createGenerationMonitor> | undefined;
function clientMonitor() {
 if (!monitor) monitor = createGenerationMonitor({
  socket: () => new WebSocket(apiWebSocketUrl('/api/ws/generation-jobs')),
  fetch: signal => fetchGenerationJobs(undefined, signal),
  visible: () => !document.hidden,
  onVisibility(callback) {
   document.addEventListener('visibilitychange', callback);
   window.addEventListener('online', callback);
   return () => { document.removeEventListener('visibilitychange', callback); window.removeEventListener('online', callback); };
  },
  loadCursor: () => JSON.parse(sessionStorage.getItem('clone-voice.generation-cursor.v1') ?? '[]'),
  saveCursor: cursor => sessionStorage.setItem('clone-voice.generation-cursor.v1', JSON.stringify(cursor)),
 });
 return monitor;
}
export const generationState = readable(initialGenerationState(), set => {
 if (typeof window === 'undefined') return;
 return clientMonitor().subscribe(set);
});
export function requestGenerationSync() { if (typeof window !== 'undefined') clientMonitor().sync(); }
export function rememberGenerationJobs(jobs: GenerationJob[]) { if (typeof window !== 'undefined') clientMonitor().accept(jobs); }
export function dismissGenerationNotice(id: string) { monitor?.dismiss(id); }
