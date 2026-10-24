<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
 import { onDestroy, onMount } from 'svelte';
 import HelpPopover from '$lib/components/HelpPopover.svelte';
 import { apiFetch } from '$lib/studio/api';
 import { productionKinds, productionLabels, type ProductionKind, type ProductionPromptsResponse } from '$lib/studio/ai-prompts';
 let { onNotice }: { onNotice?: (type: 'success' | 'error' | 'info', text: string) => void } = $props();
 let server = $state<ProductionPromptsResponse | null>(null);
 let selectedKind = $state<ProductionKind>('sound_effect');
 let drafts = $state<Partial<Record<ProductionKind, string>>>({});
 let baseline = $state<Partial<Record<ProductionKind, string>>>({});
 let editingRevision = $state(0);
 let busy = $state(false);
 let error = $state('');
 let status = $state('');
 let conflict = $state(false);
 let alive = true;
 const requests = new Set<AbortController>();
 const template = $derived(server?.templates.find(item => item.id === selectedKind));
 const currentDraft = $derived(drafts[selectedKind] ?? '');
 const currentDirty = $derived(currentDraft !== (baseline[selectedKind] ?? ''));
 const anyDirty = $derived(productionKinds.some(kind => (drafts[kind] ?? '') !== (baseline[kind] ?? '')));

 async function request(init?: RequestInit): Promise<ProductionPromptsResponse> {
  const controller = new AbortController(); requests.add(controller);
  try {
   const response = await apiFetch('/api/ai/production/prompts', { ...init, signal: controller.signal });
   return await response.json();
  } finally { requests.delete(controller); }
 }
 function install(next: ProductionPromptsResponse) {
  server = next;
  baseline = Object.fromEntries(next.templates.map(item => [item.id, item.prompt]));
  drafts = { ...baseline };
  editingRevision = next.revision;
  conflict = false;
 }
 function receive(next: ProductionPromptsResponse) {
  const preserve = Boolean(server && anyDirty);
  server = next;
  if (!preserve) install(next);
  else if (next.revision !== editingRevision) conflict = true;
 }
 async function refresh() {
  if (busy) return;
  busy = true; error = ''; status = '';
  try { const next = await request(); if (alive) receive(next); }
  catch (cause) { if (alive) error = cause instanceof Error ? cause.message : String(cause); }
  finally { if (alive) busy = false; }
 }
 function rebase(keepEdits: boolean) {
  if (!server) return;
  const pending = Object.fromEntries(productionKinds.filter(kind => (drafts[kind] ?? '') !== (baseline[kind] ?? '')).map(kind => [kind, drafts[kind] ?? '']));
  install(server);
  if (keepEdits) drafts = { ...drafts, ...pending };
  error = '';
  status = keepEdits ? t('promptmgr.kept') : t('promptmgr.loaded');
 }
 async function save(reset = false) {
  if (busy || !server || conflict) return;
  const kind = selectedKind;
  const value = drafts[kind]?.trim() ?? '';
  if (!reset && (!value || value.length > 8000)) { error = t('promptmgr.length'); return; }
  const pending = Object.fromEntries(productionKinds.filter(key => key !== kind && (drafts[key] ?? '') !== (baseline[key] ?? '')).map(key => [key, drafts[key] ?? '']));
  busy = true; error = ''; status = '';
  try {
   const next = await request({ method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: editingRevision, updates: { [kind]: reset ? null : value } }) });
   if (!alive) return;
   install(next); drafts = { ...drafts, ...pending };
   status = reset ? t('promptmgr.reset') : t('promptmgr.saved');
   onNotice?.('success', status);
  } catch (cause) {
   if (!alive) return;
   error = cause instanceof Error ? cause.message : String(cause);
   // Failed saves preserve every draft. Adopting a new revision requires an explicit choice.
   try { const next = await request(); if (alive) receive(next); } catch { /* Preserve the original failure and drafts. */ }
  } finally { if (alive) busy = false; }
 }
 onMount(() => { void refresh(); });
 onDestroy(() => { alive = false; requests.forEach(controller => controller.abort()); });
</script>

<section class="prompt-manager" aria-label={t('promptmgr.title')}>
 <header><div class="title-line"><h2>{t('promptmgr.title')}</h2><HelpPopover label={t('promptmgr.title')} text={t('promptmgr.help')} /></div><button class="secondary-action" disabled={busy} onclick={refresh}>{t('promptmgr.refresh')}</button></header>
 {#if error}<div class="feedback error" role="alert">{error}<p>{t('promptmgr.errorHint')}</p></div>{/if}
 {#if status}<div class="feedback" role="status">{status}</div>{/if}
 {#if busy}<p role="status">{t('promptmgr.busy')}</p>{/if}
 {#if server}
  <div class="field-line"><div><label for="production-prompt-kind">{t('promptmgr.kind')}</label><select id="production-prompt-kind" bind:value={selectedKind} disabled={busy}>{#each productionKinds as kind}<option value={kind}>{productionLabels[kind]}</option>{/each}</select></div><span>{template?.customized ? t('promptmgr.custom') : t('promptmgr.builtin')} · {t('promptmgr.revision', { n: server.revision })}</span></div>
  <label for="production-system-prompt">{t('promptmgr.system')}</label>
  <textarea id="production-system-prompt" rows="10" maxlength="8000" value={currentDraft} disabled={busy} oninput={event => drafts = { ...drafts, [selectedKind]: event.currentTarget.value }} spellcheck="false"></textarea>
  <div class="field-line"><small>{currentDirty ? t('promptmgr.dirty') : t('promptmgr.clean')}</small><small>{t('promptmgr.count', { count: currentDraft.length.toLocaleString() })}</small></div>
  {#if conflict}
   <div class="feedback warning" role="alert"><strong>{t('promptmgr.conflict')}</strong><p>{t('promptmgr.conflictBody')}</p><details><summary>{t('promptmgr.latest')}</summary><textarea aria-label={t('promptmgr.latestLabel')} rows="6" readonly value={template?.prompt ?? ''}></textarea></details><div class="actions"><button class="secondary-action" disabled={busy} onclick={() => rebase(true)}>{t('promptmgr.keepMine')}</button><button class="secondary-action" disabled={busy} onclick={() => rebase(false)}>{t('promptmgr.useLatest')}</button></div></div>
  {/if}
  <div class="actions"><button class="primary-action" disabled={busy || conflict || !currentDirty || !currentDraft.trim()} onclick={() => save(false)}>{t('promptmgr.save')}</button><button class="secondary-action" disabled={busy || conflict || (!template?.customized && !currentDirty)} onclick={() => save(true)}>{t('promptmgr.restore')}</button></div>
  <details><summary>{t('promptmgr.showDefault')}</summary><textarea aria-label={t('promptmgr.defaultLabel')} rows="7" readonly value={template?.default_prompt ?? ''}></textarea></details>
 {/if}
</section>

<style>
 .prompt-manager{display:grid;gap:14px;padding:22px;border:1px solid var(--border);border-radius:12px;background:var(--card);color:var(--foreground);word-break:keep-all;min-width:0}
 header,.field-line,.actions{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}header{align-items:flex-start}header>div{min-width:0;flex:1 1 320px}.field-line>div{min-width:0;flex:1}.field-line>span{font-size:12px;color:var(--muted-foreground)}
 h2,p{margin:0}h2{font-size:19px}p,small{color:var(--muted-foreground);line-height:1.65}p{font-size:13px}small{font-size:12px}label{font-size:13px;font-weight:600}
 select,textarea{width:100%;max-width:100%;min-width:0;box-sizing:border-box;border:1px solid var(--border);border-radius:8px;padding:11px;background:var(--background);color:var(--foreground);font:inherit;font-size:13px;line-height:1.65}select{margin-top:6px;min-height:42px}textarea{resize:vertical;white-space:pre-wrap;overflow-wrap:anywhere;word-break:normal}
 button:disabled{opacity:.5;cursor:not-allowed}select:focus-visible,textarea:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.actions{justify-content:flex-start}.feedback{display:grid;gap:9px;padding:13px;border:1px solid var(--border);border-radius:8px;background:var(--accent-soft);font-size:13px;overflow-wrap:anywhere}.feedback.error,.feedback.warning{border-color:var(--warning);background:var(--background)}summary{font-size:13px;font-weight:600;cursor:pointer}details textarea{margin-top:10px}
 @media(max-width:640px){.prompt-manager{padding:14px}.field-line>div{flex-basis:100%}.actions>button{flex:1 1 200px}}
</style>
