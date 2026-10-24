<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
 import { onDestroy, onMount, tick } from 'svelte';
 import { apiFetch } from '$lib/studio/api';
 import HelpPopover from '$lib/components/HelpPopover.svelte';
 import { productionLabels, validCoverSettings, validProductionAssist, type CoverSettings, type ProductionKind, type ProductionAssistResponse } from '$lib/studio/ai-prompts';
 let {
  panelId = 'production', kinds = ['sound_effect', 'music', 'song'], contextKey = '', initialBrief = '',
  currentSettings = null, disabled = false, allowApply = false, onApply
 }: {
  panelId?: string; kinds?: ProductionKind[]; contextKey?: string; initialBrief?: string;
  currentSettings?: CoverSettings | null; disabled?: boolean; allowApply?: boolean;
  onApply?: (result: ProductionAssistResponse) => void | Promise<void>;
 } = $props();
 let kind = $state<ProductionKind>('sound_effect');
 let brief = $state('');
 let busy = $state(false);
 let applying = $state(false);
 let error = $state('');
 let status = $state('');
 let result = $state<ProductionAssistResponse | null>(null);
 let resultContext = $state('');
 let applied = $state(false);
 let alive = true;
 let serial = 0;
 let controller: AbortController | null = null;
 const fingerprint = $derived(JSON.stringify({ kind, brief: brief.trim(), contextKey, settings: kind === 'cover' ? currentSettings : null }));
 const stale = $derived(Boolean(result && (resultContext !== fingerprint || result.kind !== kind)));
 const applyLabel = $derived(kind === 'cover' ? t('assist.applyCover') : t('assist.applySound'));
 const canApply = $derived(Boolean(result && onApply && allowApply && !stale && !busy && !applying && !disabled && !applied && (kind === 'cover' || kind === 'sound_effect')));
 const qualityLabels = $derived({ fast: t('tts.set.quality.fast'), balanced: t('tts.set.quality.balanced'), quality: t('tts.set.quality.high') });
 $effect(() => { if (!kinds.includes(kind)) kind = kinds[0] ?? 'sound_effect'; });
 onMount(() => { brief = initialBrief; });
 onDestroy(() => { alive = false; serial += 1; controller?.abort(); });

 async function assist() {
  if (busy || applying || disabled) return;
  const value = brief.trim();
  if (!value || value.length > 6000) { error = t('assist.briefLength'); return; }
  if (kind === 'cover' && !validCoverSettings(currentSettings)) { error = t('assist.coverSettings'); return; }
  const requestedKind = kind, submitted = fingerprint, requestId = ++serial;
  controller = new AbortController();
  busy = true; error = ''; status = '';
  try {
   const response = await apiFetch('/api/ai/production/assist', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
    body: JSON.stringify({ kind: requestedKind, brief: value, ...(requestedKind === 'cover' ? { current_settings: currentSettings } : {}) })
   });
   const next: unknown = await response.json();
   if (!alive || requestId !== serial) return;
   if (submitted !== fingerprint) {
    status = t('assist.changed');
    return;
   }
   if (!validProductionAssist(next, requestedKind)) throw new Error(t('assist.invalid'));
   result = next; resultContext = submitted; applied = false;
   status = t('assist.received');
  } catch (cause) {
   if (alive && requestId === serial) error = cause instanceof Error ? cause.message : String(cause);
  } finally { if (alive && requestId === serial) { busy = false; controller = null; } }
 }
 async function applyResult() {
  if (!canApply || !result || !onApply || resultContext !== fingerprint) return;
  if (kind === 'sound_effect' && result.generation_prompt.length > 2000) {
   error = t('assist.tooLong'); return;
  }
  applying = true; error = ''; status = '';
  try {
   await onApply(result);
   await tick();
   if (!alive) return;
   resultContext = fingerprint; applied = true;
   status = kind === 'cover' ? t('assist.appliedCover') : t('assist.appliedSound');
  } catch (cause) { if (alive) error = cause instanceof Error ? cause.message : String(cause); }
  finally { if (alive) applying = false; }
 }
 async function copyResult() {
  if (!result) return;
  const text = [result.generation_prompt, result.lyrics, result.structure, result.advice].filter(Boolean).join('\n\n');
  try { await navigator.clipboard.writeText(text); status = t('assist.copied'); }
  catch { error = t('assist.clipboard'); }
 }
</script>

<section class="production-assist" aria-label={t('assist.title')}>
 <header class="assist-heading"><h2>{t('assist.title')}</h2><HelpPopover label={t('assist.title')} text={kind === 'cover' ? t('assist.helpCover') : t('assist.helpSound')} /></header>
 {#if kinds.length > 1}<div class="request-kind"><label for={panelId + '-production-kind'}>{t('assist.kind')}</label><select id={panelId + '-production-kind'} bind:value={kind} disabled={busy || applying || disabled}>{#each kinds as item (item)}<option value={item}>{productionLabels[item]}</option>{/each}</select></div>{/if}
 <label for={panelId + '-production-brief'}>{t('assist.brief')}</label>
 <textarea id={panelId + '-production-brief'} aria-label={t('assist.brief')} rows="4" maxlength="6000" bind:value={brief} disabled={applying || disabled} placeholder={kind === 'cover' ? t('assist.ph.cover') : kind === 'song' ? t('assist.ph.song') : kind === 'music' ? t('assist.ph.music') : t('assist.ph.sound')}></textarea>
 <div class="request-actions"><small>{t('assist.count', { count: brief.length.toLocaleString() })}</small>{#if kind === 'sound_effect' && initialBrief}<button class="secondary-action" disabled={busy || applying || disabled} onclick={() => { brief = initialBrief; status = ''; }}>{t('assist.import')}</button>{/if}<button class="primary-action" disabled={busy || applying || disabled || !brief.trim()} onclick={assist}>{busy ? t('assist.waiting') : t('assist.ask')}</button></div>
 {#if error}<div class="feedback error" role="alert">{error}<p>{t('assist.errorHint')}</p></div>{/if}
 {#if status}<div class="feedback" role="status">{status}</div>{/if}
 {#if busy}<p role="status">{t('assist.writing')}</p>{/if}
 {#if result}
  <div class="assist-result">
   <div class="result-heading"><h3>{t('assist.result', { kind: productionLabels[result.kind] })}</h3></div>
   {#if stale}<div class="feedback warning" role="status">{t('assist.stale')}</div>{/if}
   {#if result.generation_prompt}<label for={panelId + '-result-prompt'}>{t('assist.resultPrompt')}</label><textarea id={panelId + '-result-prompt'} aria-label={t('assist.resultPrompt')} rows="5" readonly value={result.generation_prompt}></textarea>{/if}
   {#if result.lyrics}<label for={panelId + '-result-lyrics'}>{t('assist.lyrics')}</label><textarea id={panelId + '-result-lyrics'} aria-label={t('assist.lyrics')} rows="8" readonly value={result.lyrics}></textarea>{/if}
   {#if result.structure}<label for={panelId + '-result-structure'}>{t('assist.structure')}</label><textarea id={panelId + '-result-structure'} aria-label={t('assist.structure')} rows="4" readonly value={result.structure}></textarea>{/if}
   {#if result.settings}<dl class="recommended-settings" aria-label={t('assist.recommended')}><div><dt>{t('tts.set.quality')}</dt><dd>{qualityLabels[result.settings.quality]}</dd></div><div><dt>{t('assist.cfg')}</dt><dd>{result.settings.cfg_scale.toFixed(1)}</dd></div><div><dt>{t('assist.pitch')}</dt><dd>{t('assist.semitones', { n: result.settings.pitch_shift })}</dd></div><div><dt>{t('assist.autoShift')}</dt><dd>{result.settings.auto_shift ? t('models.use') : t('assist.off')}</dd></div><div><dt>{t('assist.separate')}</dt><dd>{result.settings.separate_vocals ? t('models.use') : t('assist.off')}</dd></div><div><dt>{t('assist.mix')}</dt><dd>{result.settings.mix_accompaniment ? t('models.use') : t('assist.off')}</dd></div></dl>{/if}
   <div class="advice" aria-label={t('assist.advice')}><strong>{t('assist.advice')}</strong><p>{result.advice}</p></div>
   <div class="result-actions"><button class="secondary-action" disabled={busy || applying} onclick={copyResult}>{t('assist.copy')}</button>{#if result.kind === 'cover' || result.kind === 'sound_effect'}<button class="primary-action" disabled={!canApply} onclick={applyResult}>{applyLabel}</button>{/if}</div>
   {#if result.kind === 'sound_effect' && !allowApply}<small>{t('assist.pickSound')}</small>{/if}
  </div>
 {/if}
</section>

<style>
 .production-assist{display:grid;gap:13px;min-width:0;padding:22px;border:1px solid var(--border);border-radius:14px;background:var(--card);color:var(--foreground);word-break:keep-all}h2,h3,p{margin:0}h2{font-size:19px}h3{font-size:15px}.assist-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}p,small{color:var(--muted-foreground);line-height:1.65}p{font-size:13px}small{font-size:12px}label{font-size:13px;font-weight:600}
 select,textarea{width:100%;max-width:100%;min-width:0;box-sizing:border-box;border:1px solid var(--border);border-radius:8px;padding:11px;background:var(--background);color:var(--foreground);font:inherit;font-size:13px;line-height:1.65}select{min-height:42px}textarea{resize:vertical;white-space:pre-wrap;overflow-wrap:anywhere;word-break:normal}.request-kind{display:grid;gap:7px;max-width:380px}.request-actions,.result-actions,.result-heading{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.request-actions>small{flex:1 1 240px}.result-heading{justify-content:space-between}
 button:disabled{opacity:.5;cursor:not-allowed}textarea:focus-visible,select:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.feedback{display:grid;gap:7px;padding:13px;border:1px solid var(--border);border-radius:8px;background:var(--accent-soft);font-size:13px;overflow-wrap:anywhere}.feedback.error,.feedback.warning{border-color:var(--warning);background:var(--background)}.assist-result{display:grid;gap:12px;min-width:0;border-top:1px solid var(--border-soft);padding-top:18px}.advice p{white-space:pre-wrap;overflow-wrap:anywhere;margin-top:6px}.advice strong{font-size:13px}.recommended-settings{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0;background:var(--background);border-radius:8px;padding:14px}.recommended-settings dt{font-size:12px;color:var(--muted-foreground)}.recommended-settings dd{margin:5px 0 0;font-size:13px;font-weight:600}
 @media(max-width:640px){.production-assist{padding:14px}.recommended-settings{grid-template-columns:repeat(2,minmax(0,1fr))}.request-actions>button,.result-actions>button{flex:1 1 190px}}
</style>
