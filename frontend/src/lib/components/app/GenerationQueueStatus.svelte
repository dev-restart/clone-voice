<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
 import { onMount } from 'svelte';
 import { AudioLines, Bell, LoaderCircle } from '@lucide/svelte';
 import { languages } from '$lib/studio/api';
 import { generationState, dismissGenerationNotice, requestGenerationSync, isActiveGeneration, type GenerationJob } from '$lib/studio/generation';
 import type { ContentItem } from '$lib/studio/types';

 let { contents, onOpen }: { contents: ContentItem[]; onOpen: (id: string) => void | Promise<void> } = $props();
 let notifyEnabled = $state(false);
 let permission = $state<NotificationPermission | 'unsupported'>('unsupported');
 let noticeMessage = $state('');
 const notified = new Set<string>();
 const nativeNotifications = new Set<Notification>();
 const active = $derived($generationState.jobs.filter(isActiveGeneration));
 const finished = $derived($generationState.finished);
 const running = $derived(active.find(job => job.status === 'running') ?? active[0]);
 const connectionLabel = $derived($generationState.connection === 'live' ? t('queue.live') : $generationState.connection === 'connecting' ? t('queue.connecting') : $generationState.connection === 'fallback' ? t('queue.fallback') : t('queue.recovering'));
 function languageLabel(code: string) { return languages.find(item => item.code === code)?.label ?? code; }
 function titleFor(job: GenerationJob) { return contents.find(item => item.id === job.content_id)?.title ?? t('queue.jobFallback'); }
 function refreshPermission() { permission = typeof Notification !== 'undefined' && window.isSecureContext ? Notification.permission : 'unsupported'; }
 function savePreference() {
  try { localStorage.setItem('clone-voice.generation-notifications.v1', notifyEnabled ? 'true' : 'false'); }
  catch { noticeMessage = t('queue.prefSession'); }
 }
 async function toggleNotifications() {
  refreshPermission();
  if (notifyEnabled) { notifyEnabled = false; savePreference(); return; }
  if (permission === 'unsupported') { noticeMessage = t('queue.unsupported'); return; }
  try {
   // Permission is requested only from this explicit user click.
   if (permission === 'default') permission = await Notification.requestPermission();
   notifyEnabled = permission === 'granted'; savePreference();
   noticeMessage = notifyEnabled ? t('queue.enabled') : t('queue.denied');
  } catch { noticeMessage = t('queue.permissionFail'); }
 }
 onMount(() => {
  refreshPermission();
  try { notifyEnabled = permission === 'granted' && localStorage.getItem('clone-voice.generation-notifications.v1') === 'true'; } catch { /* Optional preference. */ }
  const stop = generationState.subscribe(state => {
   for (const job of state.finished) {
    if (notified.has(job.id)) continue;
    notified.add(job.id);
    if (!notifyEnabled || typeof Notification === 'undefined' || Notification.permission !== 'granted' || (!document.hidden && document.hasFocus())) continue;
    try {
     // No draft text or title is exposed on the OS lock screen.
     const notification = new Notification(job.status === 'completed' ? t('queue.notify.done') : t('queue.notify.failed'), {
      body: t('queue.notify.body', { language: languageLabel(job.language) }), tag: `clone-voice-${job.batch_id}`,
     });
     nativeNotifications.add(notification);
     notification.onclick = () => { window.focus(); void onOpen(job.content_id); notification.close(); nativeNotifications.delete(notification); };
     notification.onclose = () => nativeNotifications.delete(notification);
    } catch { noticeMessage = t('queue.notifyFail'); }
   }
  });
  return () => { stop(); for (const notification of nativeNotifications) notification.close(); };
 });
</script>

<div class="queue-connection" aria-label={t('queue.region')}>
 <span><AudioLines size={14} aria-hidden="true"/>{connectionLabel}{active.length ? ' · ' + t('queue.jobs', { count: active.length }) : ''}</span>
 <button onclick={toggleNotifications} aria-pressed={notifyEnabled}><Bell size={14} aria-hidden="true"/>{notifyEnabled ? t('queue.notifyOff') : t('queue.notifyOn')}</button>
 {#if $generationState.error}<button onclick={requestGenerationSync}>{t('queue.reconnect')}</button>{/if}
</div>
{#if noticeMessage}<p class="notification-note" role="status">{noticeMessage}</p>{/if}
{#if $generationState.error}<p class="notification-note" role="status">{$generationState.error}</p>{/if}
{#if running}
 <aside class="queue-status" aria-label={t('queue.running')}>
  <LoaderCircle size={17} class="spin" aria-hidden="true"/>
  <div><strong aria-live="polite">{running.status === 'running' ? t('tts.status.running') : t('queue.waiting')} · {languageLabel(running.language)}{running.progress ? ` · ${running.progress.percent}%` : ''}</strong><span>{titleFor(running)}{active.length > 1 ? ' · ' + t('queue.othersWaiting', { count: active.length - 1 }) : ''}</span><small>{running.progress?.message || running.message}</small>
   {#if running.progress}<progress max="100" value={running.progress.percent} aria-label={t('queue.progress')}></progress>{/if}
  </div><button onclick={() => onOpen(running.content_id)}>{t('queue.open')}</button>
 </aside>
{/if}
{#if finished.length}
 <section class="completion-list" aria-label={t('queue.completed')}>
  {#each finished.slice(0, 3) as job (job.id)}
   <div class="queue-status" class:failed={job.status === 'failed'} role="status"><AudioLines size={17} aria-hidden="true"/>
    <div><strong>{job.status === 'completed' ? t('queue.done') : t('queue.failedShort')} · {languageLabel(job.language)}</strong><span>{titleFor(job)}</span></div>
    <button onclick={() => onOpen(job.content_id)}>{t('queue.open')}</button><button class="close" aria-label={t('queue.dismiss')} onclick={() => dismissGenerationNotice(job.id)}>×</button>
   </div>
  {/each}
  {#if finished.length > 3}<small>{t('queue.moreFinished', { count: finished.length - 3 })}</small>{/if}
 </section>
{/if}

<style>
 .queue-connection {display:flex;align-items:center;justify-content:flex-end;gap:10px;flex-wrap:wrap;margin-bottom:12px;color:var(--muted-foreground);font-size:12px;}
 .queue-connection span,.queue-connection button{display:inline-flex;align-items:center;gap:5px}.queue-connection button{padding:5px 8px;border:1px solid var(--border);border-radius:6px;background:var(--card);font-size:12px;cursor:pointer;}
 .notification-note{font-size:12px;line-height:1.6;color:var(--muted-foreground);margin:0 0 12px;word-break:keep-all;}
 .queue-status{display:flex;align-items:center;gap:12px;margin-bottom:12px;padding:13px 16px;border:1px solid var(--border);border-radius:10px;background:var(--accent-soft);color:var(--foreground);min-width:0;}
 .queue-status>div{flex:1;min-width:0;display:grid;gap:4px}.queue-status strong{font-size:12px}.queue-status span{font-size:11px;color:var(--muted-foreground);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.queue-status small,.completion-list>small{font-size:11px;color:var(--muted-foreground)}
 .queue-status button{border:1px solid var(--border);border-radius:7px;padding:8px 11px;white-space:nowrap;background:var(--card);font-size:12px;cursor:pointer}.queue-status .close{padding:6px;border:0;background:transparent}.queue-status.failed{border-color:var(--warning)}
 .queue-status progress{width:100%;height:5px;accent-color:var(--accent)}button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
 :global(.queue-status .spin){animation:queue-spin 1s linear infinite}@keyframes queue-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){:global(.queue-status .spin){animation:none}}
 @media(max-width:560px){.queue-status{gap:8px;padding:11px}.queue-status button{padding:8px;font-size:11px}.queue-connection{justify-content:space-between}}
</style>
