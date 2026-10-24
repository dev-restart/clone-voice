<script lang="ts">
import { onMount, untrack } from 'svelte';
import { AlertCircle, Check, ChevronDown, Languages, LoaderCircle, Mic, RefreshCw, Save, Settings2, Sparkles } from '@lucide/svelte';
import HelpPopover from '$lib/components/HelpPopover.svelte';
import { Badge } from '$lib/components/ui/badge';
import { Button } from '$lib/components/ui/button';
import { Switch } from '$lib/components/ui/switch';
import { LOCALES, i18n, t, type Locale } from '$lib/i18n/index.svelte';
import { apiFetch, languages } from '$lib/studio/api';
import type { StudioPreferences } from '$lib/studio/preferences';

type TranslationMode = 'auto' | 'apple' | 'selected';
type PlatformInfo = { is_mac: boolean; apple_speech_supported: boolean; apple_speech_message?: string };
type TranslationInfo = { mode: TranslationMode; effective_provider?: string; effective_model?: string; message?: string; apple_available: boolean };
type ProviderCatalog = { translation: TranslationInfo; providers?: { id: string; label: string }[]; api_providers?: { id: string; label: string }[] };
type TranslationTest = { ok: boolean; provider?: string; model?: string; elapsed_ms?: number; source_text?: string; translations?: Record<string, string>; detail?: string };

let { preferences, onSave, onNotice, refreshRevision = 0 }: {
preferences: StudioPreferences;
refreshRevision?: number;
onSave: (value: StudioPreferences) => Promise<void>;
onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
} = $props();

const defaultPreferences: StudioPreferences = { start_menu: 'tts', source_language: 'ko', stt_provider: 'apple-speech', show_auxiliary_tools: false };
const startChoices = $derived<{ value: StudioPreferences['start_menu']; label: string }[]>([
{ value: 'tts', label: t('nav.tts') }, { value: 'sfx', label: t('nav.sfx') },
{ value: 'changer', label: t('nav.changer') }, { value: 'home', label: t('nav.home') },
]);

let draft = $state<StudioPreferences>({ ...defaultPreferences });
let savedPreferences = $state<StudioPreferences>({ ...defaultPreferences });
let preferencesSaving = $state(false);
let preferencesError = $state('');
let externalPreferencesChanged = $state(false);
let initialized = false;
let lastPropsKey = '';
let disposed = false;
let statusRevision = 0;
let platform = $state<PlatformInfo | null>(null);
let platformError = $state('');
let catalog = $state<ProviderCatalog | null>(null);
let statusLoading = $state(false);
let catalogError = $state('');
let translationMode = $state<TranslationMode>('auto');
let savedTranslationMode = $state<TranslationMode>('auto');
let translationSaving = $state(false);
let translationSaveError = $state('');
let testing = $state(false);
let testResult = $state<TranslationTest | null>(null);
let testError = $state('');

const preferencesDirty = $derived(preferencesKey(draft) !== preferencesKey(savedPreferences));
const translationDirty = $derived(translationMode !== savedTranslationMode);
const statusBusy = $derived(statusLoading || translationSaving || testing);

function preferencesKey(value: StudioPreferences) {
return JSON.stringify([value.start_menu, value.source_language, value.stt_provider, value.show_auxiliary_tools]);
}

$effect(() => {
const incoming = { ...preferences };
const incomingKey = preferencesKey(incoming);
untrack(() => {
if (initialized && incomingKey === lastPropsKey) return;
lastPropsKey = incomingKey;
const localDirty = preferencesKey(draft) !== preferencesKey(savedPreferences);
if (!initialized || !localDirty) {
draft = incoming;
externalPreferencesChanged = false;
} else {
externalPreferencesChanged = preferencesKey(draft) !== incomingKey;
}
savedPreferences = { ...incoming };
initialized = true;
});
});

function errorMessage(error: unknown, fallback: string) {
return error instanceof Error && error.message ? error.message : fallback;
}

function providerLabel(provider?: string) {
if (!provider) return t('prefs.noProvider');
const selected = [...(catalog?.providers ?? []), ...(catalog?.api_providers ?? [])].find(item => item.id === provider);
if (selected) return selected.label;
const labels: Record<string, string> = { apple: t('prefs.appleTranslation'), 'apple-foundation-models': t('prefs.appleTranslation'), gemini: 'Gemini', ollama: 'Ollama', lmstudio: 'LM Studio', 'lm-studio': 'LM Studio' };
if (labels[provider]) return labels[provider];
return t('prefs.configuredProvider');
}

function languageLabel(code: string) {
return languages.find((item) => item.code === code)?.label || code;
}

function elapsedLabel(value?: number) {
if (typeof value !== 'number' || !Number.isFinite(value)) return '';
return value >= 1000 ? t('prefs.seconds', { value: (value / 1000).toFixed(2) }) : `${Math.round(value)}ms`;
}

async function refreshStatus() {
if (disposed) return;
const revision = ++statusRevision;
testResult = null; testError = "";
statusLoading = true;
const results = await Promise.allSettled([
apiFetch('/api/studio/preferences').then((response) => response.json() as Promise<{ platform: PlatformInfo }>),
apiFetch('/api/ai/providers').then((response) => response.json() as Promise<ProviderCatalog>),
]);
if (disposed || revision !== statusRevision) return;
const platformResponse = results[0];
if (platformResponse.status === 'fulfilled') {
platform = platformResponse.value.platform;
platformError = '';
} else {
platformError = errorMessage(platformResponse.reason, t('prefs.platformFail'));
}
const catalogResponse = results[1];
if (catalogResponse.status === 'fulfilled' && catalogResponse.value.translation) {
const incoming = catalogResponse.value;
if (!catalog || translationMode === savedTranslationMode) translationMode = incoming.translation.mode;
savedTranslationMode = incoming.translation.mode;
catalog = incoming;
catalogError = '';
} else {
catalogError = catalogResponse.status === 'rejected'
? errorMessage(catalogResponse.reason, t('prefs.catalogFail'))
: t('prefs.catalogMissing');
}
statusLoading = false;
}

async function savePreferences() {
if (preferencesSaving || !preferencesDirty) return;
const snapshot = { ...draft };
preferencesSaving = true;
preferencesError = '';
try {
await onSave(snapshot);
if (disposed) return;
savedPreferences = snapshot;
externalPreferencesChanged = false;
onNotice('success', t('prefs.savedNotice'));
} catch (error) {
if (disposed) return;
preferencesError = errorMessage(error, t('prefs.saveFailed'));
onNotice('error', preferencesError);
} finally {
if (!disposed) preferencesSaving = false;
}
}

function restorePreferences() {
draft = { ...savedPreferences };
externalPreferencesChanged = false;
preferencesError = '';
}

async function saveTranslationMode() {
if (statusBusy || !translationDirty || !catalog) return;
const mode = translationMode;
translationSaving = true;
translationSaveError = '';
try {
await apiFetch('/api/ai/providers/connections', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ translation_mode: mode }) });
if (disposed) return;
savedTranslationMode = mode;
testResult = null;
testError = '';
onNotice('success', t('prefs.trSavedNotice'));
await refreshStatus();
} catch (error) {
if (disposed) return;
translationSaveError = errorMessage(error, t('prefs.trSaveFailed'));
onNotice('error', translationSaveError);
} finally {
if (!disposed) translationSaving = false;
}
}

async function testTranslation() {
if (statusBusy || translationDirty || !catalog) return;
testing = true;
testResult = null;
testError = '';
try {
const result = await apiFetch('/api/ai/translation/test', { method: 'POST' }).then((response) => response.json() as Promise<TranslationTest>);
if (disposed) return;
testResult = result;
} catch (error) {
if (disposed) return;
testError = errorMessage(error, t('prefs.trTestFailed'));
} finally {
if (!disposed) testing = false;
}
}

$effect(() => {
const changed = refreshRevision;
if (changed > 0) untrack(() => { void refreshStatus(); });
});

onMount(() => {
void refreshStatus();
return () => { disposed = true; statusRevision += 1; };
});
</script>

<section class="border-border bg-card grid min-w-0 rounded-xl border" aria-labelledby="studio-preferences-heading">
  <header class="border-border-soft flex flex-wrap items-center justify-between gap-3 border-b px-6 py-5">
    <h2 id="studio-preferences-heading" class="flex items-center gap-2 text-lg font-semibold"><Settings2 size={19} class="text-brand" aria-hidden="true" />{t('prefs.title')}</h2>
    <Button variant="ghost" size="sm" onclick={refreshStatus} disabled={statusBusy} aria-label={t('prefs.refreshLabel')}><RefreshCw size={14} class={statusLoading ? 'animate-spin' : ''} aria-hidden="true" />{statusLoading ? t('prefs.checking') : t('prefs.refresh')}</Button>
  </header>

  <div class="border-border-soft grid gap-4 border-b px-6 py-5">
    <h3 class="text-sm font-semibold">{t('prefs.defaults')}</h3>
    <fieldset class="m-0 grid gap-4 border-0 p-0" disabled={preferencesSaving}>
      <div class="grid gap-4 sm:grid-cols-3">
        <label class="grid gap-1.5 text-sm font-medium"><span class="inline-flex items-center gap-1">{t('language.switch')}<HelpPopover label={t('language.switch')} text={t('prefs.uiLanguageHelp')} /></span>
          <select class="studio-input" aria-label={t('language.switch')} value={i18n.locale} onchange={(event) => i18n.set(event.currentTarget.value as Locale)}>{#each LOCALES as item}<option value={item.code} lang={item.code}>{item.label}</option>{/each}</select></label>
        <label class="grid gap-1.5 text-sm font-medium"><span class="inline-flex items-center gap-1">{t('prefs.startMenu')}<HelpPopover label={t('prefs.startMenu')} text={t('prefs.startMenuHelp')} /></span>
          <select class="studio-input" aria-label={t('prefs.startMenu')} bind:value={draft.start_menu}>{#each startChoices as item}<option value={item.value}>{item.label}</option>{/each}</select></label>
        <label class="grid gap-1.5 text-sm font-medium"><span class="inline-flex items-center gap-1">{t('tts.source.language')}<HelpPopover label={t('tts.source.language')} text={t('prefs.sourceLanguageHelp')} /></span>
          <select class="studio-input" aria-label={t('tts.source.language')} bind:value={draft.source_language}>{#each languages as item}<option value={item.code}>{item.label}</option>{/each}</select></label>
      </div>
      <label class="flex cursor-pointer items-center gap-2.5 text-sm"><Switch checked={draft.show_auxiliary_tools} onCheckedChange={(next) => (draft.show_auxiliary_tools = next)} aria-label={t('prefs.auxiliary')} /><span class="font-medium">{t('prefs.auxiliary')}</span><HelpPopover label={t('prefs.auxiliary')} text={t('prefs.auxiliaryHelp')} /></label>
    </fieldset>
  </div>

  <div class="border-border-soft grid gap-3 border-b px-6 py-5">
    <div class="flex items-center justify-between gap-3">
      <div class="inline-flex items-center gap-1"><h3 class="flex items-center gap-2 text-sm font-semibold"><Mic size={16} aria-hidden="true" />{t('prefs.stt')}</h3><HelpPopover label={t('prefs.stt')} text={t('prefs.sttHelp')} /></div>
      {#if platform?.is_mac}<Badge variant={platform.apple_speech_supported ? 'success' : 'warning'}>{platform.apple_speech_supported ? t('prefs.macReady') : t('prefs.macNeeded')}</Badge>{/if}
    </div>
    <label class="grid max-w-md gap-1.5 text-sm font-medium"><span>{t('prefs.sttDefault')}</span>
      <select class="studio-input" aria-label={t('prefs.sttLabel')} bind:value={draft.stt_provider} disabled={preferencesSaving}>
        {#if platform?.is_mac !== false}<option value="apple-speech" disabled={platform?.apple_speech_supported === false}>{t('prefs.sttApple')}{platform?.apple_speech_supported === false ? ' · ' + t('prefs.unsupported') : ' · ' + t('prefs.recommended')}</option>{/if}
        <option value="whisper">{t('prefs.sttWhisper')}</option>
      </select></label>
    {#if platformError}<p class="inline-note error" role="status"><AlertCircle size={15} aria-hidden="true" />{platformError}</p>{:else if draft.stt_provider === 'apple-speech' && platform?.apple_speech_message}<p class="text-muted-foreground text-xs break-words">{platform.apple_speech_message}</p>{/if}
    {#if externalPreferencesChanged}<p class="inline-note" role="status">{t('prefs.externalChanged')}</p>{/if}
    {#if preferencesError}<p class="inline-note error" role="alert"><AlertCircle size={15} aria-hidden="true" />{preferencesError}</p>{/if}
    <div class="flex flex-wrap items-center justify-between gap-3 pt-1">
      <span class="text-muted-foreground text-xs" aria-live="polite">{preferencesDirty ? t('prefs.dirty') : t('prefs.clean')}</span>
      <div class="flex gap-2"><Button variant="ghost" onclick={restorePreferences} disabled={preferencesSaving || !preferencesDirty}>{t('prefs.revert')}</Button><Button onclick={savePreferences} disabled={preferencesSaving || !preferencesDirty}>{#if preferencesSaving}<LoaderCircle size={15} class="animate-spin" aria-hidden="true" />{:else}<Save size={15} aria-hidden="true" />{/if}{preferencesSaving ? t('tts.editor.saving') : t('prefs.save')}</Button></div>
    </div>
  </div>

  <div class="grid gap-3 px-6 py-5">
    <div class="flex items-center justify-between gap-3">
      <div class="inline-flex items-center gap-1"><h3 class="flex items-center gap-2 text-sm font-semibold"><Languages size={16} aria-hidden="true" />{t('prefs.translation')}</h3><HelpPopover label={t('prefs.translation')} text={translationMode === 'auto' ? t('prefs.trHelpAuto') : translationMode === 'apple' ? t('prefs.trHelpApple') : t('prefs.trHelpSelected')} /></div>
      {#if catalog?.translation.apple_available !== undefined && platform?.is_mac}<Badge variant={catalog?.translation.apple_available ? 'success' : 'warning'}>Apple {catalog?.translation.apple_available ? t('common.ready') : t('common.needsSetup')}</Badge>{/if}
    </div>
    <label class="grid max-w-md gap-1.5 text-sm font-medium"><span>{t('prefs.trDefault')}</span>
      <select class="studio-input" aria-label={t('prefs.trDefault')} bind:value={translationMode} onchange={() => { testResult = null; testError = ""; }} disabled={!catalog || statusBusy}>
        {#if platform?.is_mac !== false}<option value="auto">{t('prefs.trAuto')}</option><option value="apple">{t('prefs.trApple')}</option>{/if}<option value="selected">{t('prefs.trSelected')}</option>
      </select></label>
    {#if catalog}
      <div class="bg-muted/60 border-border grid gap-1 rounded-lg border px-3.5 py-3 text-sm"><span class="text-muted-foreground text-xs">{t('prefs.trCurrent')}</span><strong>{providerLabel(catalog.translation.effective_provider)}</strong>{#if catalog.translation.message}<p class="text-muted-foreground text-xs break-words">{catalog.translation.message}</p>{/if}</div>
      <details class="text-xs"><summary class="text-muted-foreground hover:text-foreground inline-flex cursor-pointer items-center gap-1">{t('prefs.trDetails')} <ChevronDown size={13} aria-hidden="true" /></summary><dl class="mt-2 grid gap-1.5"><div class="grid grid-cols-[80px_minmax(0,1fr)] gap-2"><dt class="text-subtle-foreground">{t('prefs.trId')}</dt><dd class="m-0 break-all">{catalog.translation.effective_provider || t('common.none')}</dd></div><div class="grid grid-cols-[80px_minmax(0,1fr)] gap-2"><dt class="text-subtle-foreground">{t('prefs.trModel')}</dt><dd class="m-0 break-all">{catalog.translation.effective_model || t('common.none')}</dd></div></dl></details>
    {/if}
    {#if catalogError}<p class="inline-note error" role="status"><AlertCircle size={15} aria-hidden="true" />{catalogError}</p>{/if}
    {#if translationSaveError}<p class="inline-note error" role="alert"><AlertCircle size={15} aria-hidden="true" />{translationSaveError}</p>{/if}
    <div class="flex flex-wrap items-center justify-between gap-3 pt-1">
      <span class="text-muted-foreground text-xs">{translationDirty ? t('prefs.trSaveFirst') : ''}</span>
      <div class="flex flex-wrap gap-2"><Button variant="secondary" onclick={testTranslation} disabled={statusBusy || translationDirty || !catalog}>{#if testing}<LoaderCircle size={15} class="animate-spin" aria-hidden="true" />{t('prefs.checking')}{:else}<Sparkles size={15} aria-hidden="true" />{t('prefs.trTest')}{/if}</Button><Button onclick={saveTranslationMode} disabled={statusBusy || !translationDirty || !catalog}>{#if translationSaving}<LoaderCircle size={15} class="animate-spin" aria-hidden="true" />{:else}<Save size={15} aria-hidden="true" />{/if}{translationSaving ? t('tts.editor.saving') : t('prefs.trSave')}</Button></div>
    </div>

    {#if testError}<p class="inline-note error" role="alert"><AlertCircle size={15} aria-hidden="true" />{testError}</p>{/if}
    {#if testResult}
      <div class="grid gap-2 rounded-lg border px-3.5 py-3 text-sm {testResult.ok ? 'border-success/30 bg-success-soft' : 'border-danger/30 bg-danger-soft'}" role="status">
        <div class="flex flex-wrap items-center justify-between gap-2"><strong class="inline-flex items-center gap-1.5">{#if testResult.ok}<Check size={15} aria-hidden="true" />{t('prefs.trOk')}{:else}<AlertCircle size={15} aria-hidden="true" />{t('prefs.trFail')}{/if}</strong>{#if elapsedLabel(testResult.elapsed_ms)}<span class="text-muted-foreground text-xs">{elapsedLabel(testResult.elapsed_ms)}</span>{/if}</div>
        {#if testResult.detail}<p class="text-xs break-words">{testResult.detail}</p>{/if}
        {#if testResult.source_text}<div class="grid gap-0.5"><span class="text-muted-foreground text-xs">{t('tts.queue.original')}</span><p class="break-words">{testResult.source_text}</p></div>{/if}
        {#each Object.entries(testResult.translations || {}) as [code, translated]}<div class="grid gap-0.5"><span class="text-muted-foreground text-xs">{languageLabel(code)}</span><p class="break-words">{translated}</p></div>{/each}
        {#if testResult.provider || testResult.model}<details class="text-xs"><summary class="text-muted-foreground cursor-pointer">{t('prefs.trTestInfo')}</summary><dl class="mt-2 grid gap-1"><div class="grid grid-cols-[60px_minmax(0,1fr)] gap-2"><dt class="text-subtle-foreground">{t('prefs.trConnection')}</dt><dd class="m-0 break-all">{testResult.provider || t('prefs.unknown')}</dd></div><div class="grid grid-cols-[60px_minmax(0,1fr)] gap-2"><dt class="text-subtle-foreground">{t('prefs.trModel')}</dt><dd class="m-0 break-all">{testResult.model || t('prefs.unknown')}</dd></div></dl></details>{/if}
      </div>
    {/if}
  </div>
</section>

<style>
  .inline-note { display: flex; align-items: flex-start; gap: 7px; margin: 0; padding: 10px; border-radius: 8px; background: var(--muted); font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
  .inline-note.error { background: var(--danger-soft); color: var(--danger); }
  details > summary { list-style: none; }
  details > summary::-webkit-details-marker { display: none; }
</style>
