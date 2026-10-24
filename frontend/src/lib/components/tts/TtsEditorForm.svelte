<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
  import { tick, type ComponentProps } from 'svelte';
  import {
    AlertCircle,
    ArrowLeft,
    AudioLines,
    Check,
    ChevronDown,
    Clock3,
    Languages,
    LoaderCircle,
    Plus,
    RotateCcw,
    Save,
    Sparkles,
    X,
  } from '@lucide/svelte';
  import HelpPopover from '$lib/components/HelpPopover.svelte';
  import { audioUrl, languages } from '$lib/studio/api';
  import type { PronunciationRule } from '$lib/studio/types';
  import ProgressPanel from '../app/ProgressPanel.svelte';
  import TtsScriptAssist from './TtsScriptAssist.svelte';
  import TtsPronunciationEditor from './TtsPronunciationEditor.svelte';

  type QueueItem = {
    id: string;
    language: string;
    status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
    message?: string;
    parent_job_id?: string | null;
  };

  type Props = {
    selectedContentId: string;
    title: string;
    text: string;
    translations: Record<string, string>;
    selectedTargets: string[];
    busy: boolean;
    canSave: boolean;
    canGenerate: boolean;
    canTranslate: boolean;
    modelId?: string;
    speed?: number;
    generationProgress: { percent: number; message: string; elapsed: number; active: boolean };
    isDirty: boolean;
    busyAction: string;
    backupFailed: boolean;
    previewResult: { text: string; spoken_text?: string; audio_url: string } | null;
    previewStale: boolean;
    pronunciationRules: PronunciationRule[];
    dictionaryError: string;
    language: string;
    onPreview: () => void | Promise<void>;
    onPronunciationChange: (rules: PronunciationRule[]) => void;
    onBack: () => void;
    onSave: () => void | Promise<void>;
    onGenerate: (targetLanguage?: string, targetText?: string) => void | Promise<void>;
    onTranslate: (overwrite?: boolean) => void | Promise<void>;
    onTitleChange: (value: string) => void;
    onTextChange: (value: string) => void;
    onTranslationChange: (code: string, value: string) => void;
    onToggleTarget: (code: string) => void;
    onNotice: ComponentProps<typeof TtsScriptAssist>['onNotice'];
    onLanguageChange: (value: string) => void;
    onAddLanguages: (codes: string[]) => void;
    onGenerateBatch: (codes: string[]) => void | Promise<void>;
    queue?: QueueItem[];
    generationTargets: string[];
    onToggleGenerationTarget: (code: string) => void;
    onCancelQueued: (id: string) => void | Promise<void>;
    onRetryJob: (id: string) => void | Promise<void>;
  };

  let {
    selectedContentId,
    title,
    text,
    translations,
    selectedTargets,
    busy,
    canSave,
    canGenerate,
    canTranslate,
    speed = 1,
    generationProgress,
    isDirty,
    busyAction,
    backupFailed,
    previewResult,
    previewStale,
    pronunciationRules,
    dictionaryError,
    language,
    onPreview,
    onPronunciationChange,
    onBack,
    onSave,
    onGenerate,
    onTranslate,
    onTitleChange,
    onTextChange,
    onTranslationChange,
    onToggleTarget,
    onNotice,
    onLanguageChange,
    onAddLanguages,
    onGenerateBatch,
    queue = [],
    generationTargets,
    onToggleGenerationTarget,
    onCancelQueued,
    onRetryJob,
  }: Props = $props();

  let languagePickerOpen = $state(false);
  let overwriteTranslations = $state(false);
  let activeTranslation = $state<string | null>(null);
  let requestedTranslation = $state<string | null>(null);

  const sourceLanguage = $derived(language || 'ko');
  const targetChoices = $derived(languages.filter((item) => item.code !== sourceLanguage));
  const translationTabs = $derived(
    targetChoices.filter((item) => Object.prototype.hasOwnProperty.call(translations, item.code)),
  );
  const selectedLanguageCodes = $derived(
    targetChoices.filter((item) => selectedTargets.includes(item.code)).map((item) => item.code),
  );
  const selectedExistingCount = $derived(
    selectedLanguageCodes.filter((code) => translations[code]?.trim()).length,
  );
  const translationRequestCount = $derived(
    selectedLanguageCodes.filter((code) => overwriteTranslations || !translations[code]?.trim()).length,
  );
  const newTabCodes = $derived(
    selectedLanguageCodes.filter((code) => !Object.prototype.hasOwnProperty.call(translations, code)),
  );
  const activeTranslationText = $derived(activeTranslation ? translations[activeTranslation] ?? '' : '');
  const generationChoices = $derived([
    { code: sourceLanguage, label: languageLabel(sourceLanguage), text, original: true },
    ...translationTabs.map((item) => ({ ...item, text: translations[item.code] ?? '', original: false })),
  ]);
  const selectedGenerationCodes = $derived(
    generationChoices
      .filter((item) => item.text.trim() && generationTargets.includes(item.code))
      .map((item) => item.code),
  );
  const queuedCount = $derived(queue.filter((item) => item.status === 'queued').length);
  const runningCount = $derived(queue.filter((item) => item.status === 'running').length);
  const failedCount = $derived(queue.filter((item) => item.status === 'failed').length);

  const statusLabels = $derived<Record<QueueItem['status'], string>>({
    queued: t('tts.status.queued'),
    running: t('tts.status.running'),
    completed: t('tts.status.completed'),
    failed: t('tts.status.failed'),
    cancelled: t('tts.status.cancelled'),
  });

  $effect(() => {
    // A different content item must not inherit an overwrite choice.
    selectedContentId;
    languagePickerOpen = false;
    overwriteTranslations = false;
    requestedTranslation = null;
  });

  $effect(() => {
    if (requestedTranslation && translationTabs.some((item) => item.code === requestedTranslation)) {
      activeTranslation = requestedTranslation;
      requestedTranslation = null;
    } else if (!translationTabs.some((item) => item.code === activeTranslation)) {
      activeTranslation = translationTabs[0]?.code ?? null;
    }
  });

  function languageLabel(code: string): string {
    return languages.find((item) => item.code === code)?.label ?? code;
  }

  function addEmptyTabs() {
    if (!newTabCodes.length || busy) return;
    requestedTranslation = newTabCodes[0];
    onAddLanguages([...newTabCodes]);
    languagePickerOpen = false;
  }

  function translateSelected() {
    if (!translationRequestCount || !canTranslate || !text.trim() || busy) return;
    requestedTranslation = selectedLanguageCodes.find(
      (code) => overwriteTranslations || !translations[code]?.trim(),
    ) ?? null;
    onTranslate(overwriteTranslations);
  }

  async function moveTranslationTab(event: KeyboardEvent, index: number) {
    let nextIndex = index;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % translationTabs.length;
    else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + translationTabs.length) % translationTabs.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = translationTabs.length - 1;
    else return;
    event.preventDefault();
    activeTranslation = translationTabs[nextIndex].code;
    await tick();
    document.getElementById(`tts-translation-tab-${activeTranslation}`)?.focus();
  }
</script>

<div class="tts-flow">
  <header class="editor-topbar">
    <div class="editor-identity">
      <button class="back-button" type="button" onclick={onBack} disabled={busy} aria-label={t('tts.editor.back')} title={t('tts.editor.back')}>
        <ArrowLeft size={19} aria-hidden="true" />
      </button>
      <div class="title-field">
        <label for="tts-content-title">{selectedContentId ? t('tts.editor.content') : t('tts.editor.newContent')}</label>
        <input
          id="tts-content-title"
          aria-label={t('tts.editor.titleLabel')}
          value={title}
          oninput={(event) => onTitleChange(event.currentTarget.value)}
          disabled={busy}
          placeholder={t('tts.editor.titlePlaceholder')}
          maxlength="160"
        />
      </div>
    </div>
    <div class="save-actions">
      <span class:unsaved={isDirty} class="save-status" aria-live="polite">
        {#if isDirty}<span class="status-dot"></span>{t('tts.editor.unsaved')}{:else if selectedContentId}<Check size={14} aria-hidden="true" />{t('tts.editor.saved')}{:else}{t('tts.editor.notSaved')}{/if}
      </span>
      <button class="secondary-action" type="button" onclick={onSave} disabled={!canSave || busy}>
        {#if busyAction === 'saving'}<LoaderCircle size={16} class="spin" aria-hidden="true" />{:else}<Save size={16} aria-hidden="true" />{/if}
        {busyAction === 'saving' ? t('tts.editor.saving') : t('common.save')}
      </button>
    </div>
  </header>

  {#if backupFailed}
    <div class="inline-notice warning" role="status">
      <AlertCircle size={17} aria-hidden="true" />
      <p>{t('tts.editor.backupFailed')}</p>
    </div>
  {/if}

  <section class="surface script-section" aria-labelledby="tts-source-heading">
    <div class="section-heading">
      <div class="heading-copy">
        <span class="step-number" aria-hidden="true">01</span>
        <div><h2 id="tts-source-heading">{t('tts.source.title')}</h2></div>
      </div>
      <label class="source-language">
        <span>{t('tts.source.language')}</span>
        <select class="studio-input" aria-label={t('tts.source.language')} value={sourceLanguage} onchange={(event) => onLanguageChange(event.currentTarget.value)} disabled={busy}>
          {#each languages as item}<option value={item.code}>{item.label}</option>{/each}
        </select>
      </label>
    </div>

    <div class="script-editor">
      <label class="sr-only" for="tts-original-script">{t('tts.script')}</label>
      <textarea
        id="tts-original-script"
        class="studio-input script-textarea"
        aria-label={t('tts.script')}
        value={text}
        oninput={(event) => onTextChange(event.currentTarget.value)}
        disabled={busy}
        rows="8"
        placeholder={t('tts.script.placeholder')}
        spellcheck="true"
      ></textarea>
      <div class="editor-meta"><span>{t('tts.source.badge', { language: languageLabel(sourceLanguage) })}</span><span>{t('tts.chars', { count: text.length.toLocaleString() })}</span></div>
    </div>

    <div class="editor-action-row">
      <div class="action-buttons">
        <button class="secondary-action" type="button" onclick={onPreview} disabled={!canGenerate || !text.trim() || busy}>
          {#if busyAction === 'preview'}<LoaderCircle size={16} class="spin" aria-hidden="true" />{:else}<AudioLines size={16} aria-hidden="true" />{/if}
          {busyAction === 'preview' ? t('tts.preview.making') : t('tts.preview.make')}
        </button>
        <button class="primary-action" type="button" onclick={() => onGenerate(sourceLanguage, text)} disabled={!canGenerate || !text.trim() || busy}>
          <AudioLines size={17} aria-hidden="true" />{t('tts.source.generate')}
        </button>
      </div>
    </div>

    {#if !canGenerate && !busy && text.trim()}
      <p class="availability-note"><AlertCircle size={15} aria-hidden="true" />{t('tts.unavailable')}</p>
    {/if}

    {#if previewResult}
      <div class:stale={previewStale} class="preview-card">
        <div class="preview-copy">
          <strong>{t('tts.preview.title')}</strong>
          <p>{previewStale ? t('tts.preview.stale') : previewResult.spoken_text || previewResult.text}</p>
        </div>
        <audio controls preload="metadata" src={audioUrl(previewResult.audio_url)} aria-label={t('tts.preview.title')}></audio>
      </div>
    {/if}

    <details class="optional-tools">
      <summary><span><Sparkles size={16} aria-hidden="true" />{t('tts.refine')}</span><ChevronDown size={16} class="details-chevron" aria-hidden="true" /></summary>
      <div class="optional-content">
        <TtsScriptAssist {text} language={sourceLanguage} disabled={busy} onApply={onTextChange} {onNotice} />
        <TtsPronunciationEditor rules={pronunciationRules} {text} language={sourceLanguage} error={dictionaryError} onChange={onPronunciationChange} />
        <dl class="advanced-metadata"><div><dt>{t('tts.speed')}</dt><dd>{t('tts.speedValue', { value: Number.isFinite(speed) ? speed.toFixed(2) : '1.00' })}</dd></div></dl>
      </div>
    </details>
  </section>

  <section class="surface translation-section" aria-labelledby="tts-translation-heading">
    <div class="section-heading">
      <div class="heading-copy">
        <span class="step-number" aria-hidden="true">02</span>
        <div><div class="inline-flex items-center gap-1"><h2 id="tts-translation-heading">{t('tts.translate.title')} <span class="optional-badge">{t('common.optional')}</span></h2><HelpPopover label={t('tts.translate.title')} text={t('tts.translate.help')} /></div></div>
      </div>
      <button class="secondary-action" type="button" aria-expanded={languagePickerOpen} aria-controls="tts-language-picker" onclick={() => languagePickerOpen = !languagePickerOpen} disabled={busy}>
        {#if languagePickerOpen}<X size={16} aria-hidden="true" />{t('common.close')}{:else}<Plus size={16} aria-hidden="true" />{t('tts.translate.add')}{/if}
      </button>
    </div>

    {#if languagePickerOpen}
      <div id="tts-language-picker" class="language-picker">
        <fieldset disabled={busy}>
          <legend>{t('tts.translate.pick')}</legend>
          <div class="target-grid">
            {#each targetChoices as item}
              <label class:selected={selectedTargets.includes(item.code)} class="target-choice">
                <input type="checkbox" checked={selectedTargets.includes(item.code)} onchange={() => onToggleTarget(item.code)} />
                <span>{item.label}</span>
                {#if translations[item.code]?.trim()}<small>{t('tts.translate.has')}</small>{:else if Object.prototype.hasOwnProperty.call(translations, item.code)}<small>{t('tts.translate.waiting')}</small>{/if}
              </label>
            {/each}
          </div>
          {#if selectedExistingCount > 0}
            <div class="overwrite-option"><label class="inline-flex items-center gap-2"><input type="checkbox" bind:checked={overwriteTranslations} /><span>{t('tts.translate.overwrite')}</span></label><HelpPopover label={t('tts.translate.overwrite')} text={overwriteTranslations ? t('tts.translate.overwriteOn') : t('tts.translate.overwriteOff')} /></div>
          {/if}
        </fieldset>
        {#if !canTranslate}<p class="picker-help">{t('tts.translate.notReady')}</p>{/if}
        <div class="picker-actions">
          <button class="secondary-action" type="button" onclick={addEmptyTabs} disabled={busy || !newTabCodes.length}><Plus size={15} aria-hidden="true" />{t('tts.translate.addTabs')}</button>
          <button class="primary-action" type="button" onclick={translateSelected} disabled={busy || !canTranslate || !text.trim() || !translationRequestCount}>
            {#if busyAction === 'translate'}<LoaderCircle size={16} class="spin" aria-hidden="true" />{t('tts.translate.busy')}{:else}<Languages size={16} aria-hidden="true" />{translationRequestCount ? t('tts.translate.run', { count: translationRequestCount }) : t('tts.translate.runIdle')}{/if}
          </button>
        </div>
      </div>
    {/if}

    {#if translationTabs.length && activeTranslation}
      <div class="translation-workspace">
        <div class="language-tabs" role="tablist" aria-label={t('tts.translate.tabs')}>
          {#each translationTabs as item, index}
            <button
              id={`tts-translation-tab-${item.code}`}
              type="button"
              role="tab"
              aria-selected={activeTranslation === item.code}
              aria-controls={`tts-translation-panel-${item.code}`}
              tabindex={activeTranslation === item.code ? 0 : -1}
              class:active={activeTranslation === item.code}
              onclick={() => activeTranslation = item.code}
              onkeydown={(event) => moveTranslationTab(event, index)}
            >
              {item.label}{#if !translations[item.code]?.trim()}<span class="empty-tab-dot" aria-label={t('tts.translate.empty')}></span>{/if}
            </button>
          {/each}
        </div>
        <div id={`tts-translation-panel-${activeTranslation}`} role="tabpanel" aria-labelledby={`tts-translation-tab-${activeTranslation}`} class="translation-panel">
          <div class="translation-editor-heading"><label for={`tts-translated-script-${activeTranslation}`}>{t('tts.translate.versionOf', { language: languageLabel(activeTranslation) })}</label></div>
          <div class="script-editor">
            <textarea
              id={`tts-translated-script-${activeTranslation}`}
              class="studio-input script-textarea translated-textarea"
              aria-label={t('tts.translate.versionOf', { language: languageLabel(activeTranslation) })}
              value={activeTranslationText}
              oninput={(event) => activeTranslation && onTranslationChange(activeTranslation, event.currentTarget.value)}
              disabled={busy}
              rows="7"
              placeholder={t('tts.translate.placeholder', { language: languageLabel(activeTranslation) })}
              spellcheck="true"
            ></textarea>
            <div class="editor-meta"><span>{t('tts.translate.from', { language: languageLabel(sourceLanguage) })}</span><span>{t('tts.chars', { count: activeTranslationText.length.toLocaleString() })}</span></div>
          </div>
          <div class="editor-action-row">
            <div class="action-buttons">
              <button class="secondary-action" type="button" onclick={onSave} disabled={!canSave || busy}><Save size={16} aria-hidden="true" />{t('tts.translate.save')}</button>
              <button class="primary-action" type="button" onclick={() => activeTranslation && onGenerate(activeTranslation, activeTranslationText)} disabled={!canGenerate || !activeTranslationText.trim() || busy}><AudioLines size={17} aria-hidden="true" />{t('tts.translate.generate')}</button>
            </div>
          </div>
        </div>
      </div>
    {:else if !languagePickerOpen}
      <div class="translation-empty"><span class="empty-icon"><Languages size={23} aria-hidden="true" /></span><div><strong>{t('tts.translate.emptyTitle')}</strong></div></div>
    {/if}
  </section>

  <section class="surface queue-section" aria-labelledby="tts-queue-heading">
    <div class="section-heading">
      <div class="heading-copy">
        <span class="step-number" aria-hidden="true">03</span>
        <div><div class="inline-flex items-center gap-1"><h2 id="tts-queue-heading">{t('tts.queue.title')}</h2><HelpPopover label={t('tts.queue.title')} text={t('tts.queue.help')} /></div></div>
      </div>
      {#if queuedCount || runningCount || failedCount}
        <div class="queue-counts" aria-live="polite">{#if runningCount}<span class="count-active">{t('tts.queue.running', { count: runningCount })}</span>{/if}{#if queuedCount}<span>{t('tts.queue.waiting', { count: queuedCount })}</span>{/if}{#if failedCount}<span class="count-error">{t('tts.queue.failed', { count: failedCount })}</span>{/if}</div>
      {/if}
    </div>

    <div class="batch-builder">
      <fieldset disabled={busy}>
        <legend>{t('tts.queue.together')}</legend>
        <div class="generation-options">
          {#each generationChoices as item}
            <label class:checked={generationTargets.includes(item.code) && !!item.text.trim()} class:empty={!item.text.trim()} class="generation-option">
              <input type="checkbox" checked={generationTargets.includes(item.code) && !!item.text.trim()} disabled={!item.text.trim()} onchange={() => onToggleGenerationTarget(item.code)} />
              <span>{item.label}</span>{#if item.original}<small>{t('tts.queue.original')}</small>{:else if !item.text.trim()}<small>{t('tts.translate.empty')}</small>{/if}
            </label>
          {/each}
        </div>
      </fieldset>
      <button class="primary-action batch-generate" type="button" onclick={() => onGenerateBatch([...selectedGenerationCodes])} disabled={busy || !canGenerate || !selectedGenerationCodes.length}><Plus size={17} aria-hidden="true" />{selectedGenerationCodes.length ? t('tts.queue.generateSelected', { count: selectedGenerationCodes.length }) : t('tts.queue.pickLanguages')}</button>
    </div>

    {#if generationProgress.active}
      <div class="progress-slot"><ProgressPanel progress={generationProgress} fallbackMessage={t('tts.queue.fallback')} /></div>
    {/if}

    {#if queue.length}
      <ol class="queue-list" aria-label={t('tts.queue.listLabel')}>
        {#each queue as item (item.id)}
          <li class:running={item.status === 'running'} class:failed={item.status === 'failed'}>
            <span class="queue-state-icon" aria-hidden="true">
              {#if item.status === 'running'}<LoaderCircle size={17} class="spin" />{:else if item.status === 'completed'}<Check size={17} />{:else if item.status === 'failed'}<AlertCircle size={17} />{:else if item.status === 'cancelled'}<X size={17} />{:else}<Clock3 size={17} />{/if}
            </span>
            <div class="queue-item-copy"><strong>{t('tts.queue.itemTitle', { language: languageLabel(item.language) })}</strong>{#if item.message}<p>{item.message}</p>{/if}</div>
            <span class="queue-status">{statusLabels[item.status]}</span>
            {#if item.status === 'queued'}
              <button class="queue-item-action" type="button" onclick={() => onCancelQueued(item.id)} disabled={busy} aria-label={t('tts.queue.cancelLabel', { language: languageLabel(item.language) })}><X size={15} aria-hidden="true" /><span>{t('common.cancel')}</span></button>
            {:else if (item.status === 'failed' || item.status === 'cancelled') && !queue.some((child) => child.parent_job_id === item.id && ['queued', 'running', 'completed'].includes(child.status))}
              <button class="queue-item-action retry" type="button" onclick={() => onRetryJob(item.id)} disabled={busy || !canGenerate} aria-label={t('tts.queue.retryLabel', { language: languageLabel(item.language) })}><RotateCcw size={15} aria-hidden="true" /><span>{t('tts.queue.retry')}</span></button>
            {/if}
          </li>
        {/each}
      </ol>
    {:else}
      <div class="queue-empty"><Clock3 size={19} aria-hidden="true" /><p>{t('tts.queue.empty')}</p></div>
    {/if}
  </section>
</div>

<style>
  .tts-flow { display: grid; gap: 22px; min-width: 0; color: #243b30; }
  .tts-flow :global(button), .tts-flow :global(input), .tts-flow :global(textarea), .tts-flow :global(select) { font: inherit; }
  .tts-flow :global(button) { cursor: pointer; }
  .tts-flow :global(button:disabled) { cursor: not-allowed; }
  .tts-flow :global(button:focus-visible), .tts-flow :global(summary:focus-visible), .tts-flow :global(input:focus-visible), .tts-flow :global(textarea:focus-visible), .tts-flow :global(select:focus-visible) { outline: 3px solid #9ac3a8; outline-offset: 3px; }
  .tts-flow :global(.primary-action), .tts-flow :global(.secondary-action) { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 40px; padding: 10px 15px; border: 1px solid #dce5de; border-radius: 9px; font-size: 13px; font-weight: 650; line-height: 1.35; text-decoration: none; }
  .tts-flow :global(.primary-action) { background: #214638; border-color: #214638; color: #fff; box-shadow: 0 1px 2px #18352814; }
  .tts-flow :global(.secondary-action) { color: #355344; background: #fff; }
  .tts-flow :global(.primary-action:not(:disabled):hover) { background: #19392d; }
  .tts-flow :global(.secondary-action:not(:disabled):hover) { background: #f3f7f3; border-color: #b3c9b9; }
  .tts-flow :global(.primary-action:disabled), .tts-flow :global(.secondary-action:disabled) { opacity: .47; box-shadow: none; }
  .editor-topbar, .editor-identity, .save-actions { display: flex; align-items: center; }
  .editor-topbar { justify-content: space-between; gap: 24px; padding: 1px 0 4px; }
  .editor-identity { gap: 13px; min-width: 0; flex: 1; }
  .back-button { flex: 0 0 38px; display: grid; place-items: center; width: 38px; height: 38px; border: 1px solid #dce5de; border-radius: 10px; background: #fff; color: #395548; }
  .back-button:hover:not(:disabled) { background: #eff5ef; }
  .title-field { display: grid; gap: 2px; min-width: 0; flex: 1; }
  .title-field label { color: #6a7c70; font-size: 11px; font-weight: 600; letter-spacing: .03em; }
  .title-field input { width: 100%; min-width: 0; padding: 2px 0; border: 0; border-radius: 3px; background: transparent; color: #1c392b; font-size: clamp(18px, 2.2vw, 24px); font-weight: 720; letter-spacing: -.035em; }
  .title-field input::placeholder { color: #89968c; font-weight: 550; }
  .save-actions { justify-content: flex-end; gap: 13px; flex-shrink: 0; }
  .save-status { display: inline-flex; align-items: center; gap: 5px; color: #75877a; font-size: 11px; white-space: nowrap; }
  .save-status.unsaved { color: #866f37; }
  .status-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
  .surface { min-width: 0; padding: 25px; border: 1px solid #dce5de; border-radius: 15px; background: #fff; box-shadow: 0 3px 12px #223d2c03; }
  .section-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 21px; }
  .heading-copy { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
  .heading-copy > div { min-width: 0; }
  .step-number { display: inline-flex; align-items: center; justify-content: center; width: 29px; height: 29px; flex-shrink: 0; margin-top: 1px; border: 1px solid #dce8de; border-radius: 9px; background: #f2f7f1; color: #52715a; font-size: 11px; font-weight: 750; font-variant-numeric: tabular-nums; }
  .section-heading h2 { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0; color: #233f2e; font-size: 16px; font-weight: 710; line-height: 1.6; letter-spacing: -.02em; }
  .source-language { display: flex; align-items: center; gap: 8px; flex-shrink: 0; font-size: 12px; color: #66776b; }
  .source-language select { width: auto; min-width: 100px; min-height: 36px; padding: 7px 30px 7px 11px; border: 1px solid #dce5de; border-radius: 8px; background-color: #fbfcfa; color: #304b3b; font-size: 12px; }
  .script-editor { overflow: hidden; min-width: 0; border: 1px solid #dce5de; border-radius: 10px; background: #fcfdfb; transition: border-color .15s; }
  .script-editor:focus-within { border-color: #81a98d; box-shadow: 0 0 0 3px #e5efe6; }
  .script-textarea { display: block; width: 100%; min-width: 0; min-height: 205px; padding: 20px; border: 0; border-radius: 0; background: transparent; color: #2b4234; font-size: 15px; line-height: 1.95; resize: vertical; box-sizing: border-box; }
  .script-textarea:focus-visible { outline: none !important; }
  .script-textarea::placeholder { color: #96a198; }
  .script-textarea:disabled { color: #617165; background: #f5f7f4; }
  .editor-meta { display: flex; justify-content: space-between; gap: 12px; padding: 10px 17px; border-top: 1px solid #eaf0e8; color: #7d8d80; background: #f8faf6; font-size: 11px; }
  .editor-action-row { display: flex; align-items: center; justify-content: space-between; gap: 15px; margin-top: 14px; }
  .action-buttons { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; flex-shrink: 0; }
  .availability-note { display: flex; align-items: flex-start; gap: 7px; margin: 14px 0 0; color: #8b6e3b; font-size: 12px; line-height: 1.6; }
  .availability-note :global(svg) { flex-shrink: 0; margin-top: 2px; }
  .preview-card { display: grid; grid-template-columns: minmax(0, 1fr) minmax(190px, 300px); gap: 15px; align-items: center; margin-top: 17px; padding: 15px; border: 1px solid #e0eade; border-radius: 10px; background: #f4f8f1; }
  .preview-card.stale { border-color: #e9dfca; background: #fbf8f0; }
  .preview-copy { min-width: 0; }
  .preview-copy strong { font-size: 12px; }
  .preview-copy p { display: -webkit-box; overflow: hidden; margin: 4px 0 0; color: #596e60; font-size: 11px; line-height: 1.6; line-clamp: 2; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow-wrap: anywhere; }
  .preview-card audio { width: 100%; height: 35px; }
  .optional-tools { margin-top: 21px; border-top: 1px solid #e8eee6; }
  .optional-tools summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 17px 0 0; color: #657a68; font-size: 12px; font-weight: 600; list-style: none; cursor: pointer; }
  .optional-tools summary::-webkit-details-marker { display: none; }
  .optional-tools summary > span { display: inline-flex; align-items: center; gap: 8px; }
  .optional-tools[open] :global(.details-chevron) { transform: rotate(180deg); }
  .optional-content { display: grid; gap: 17px; padding-top: 19px; }
  .advanced-metadata { display: flex; flex-wrap: wrap; gap: 10px 24px; margin: 0; padding-top: 12px; border-top: 1px solid #e7eee5; }
  .advanced-metadata > div { display: flex; flex-wrap: wrap; gap: 7px; font-size: 11px; }
  .advanced-metadata dt { color: #869284; }
  .advanced-metadata dd { margin: 0; color: #5f755f; overflow-wrap: anywhere; }
  .optional-badge { padding: 2px 6px; border-radius: 5px; background: #f2f5ef; color: #85937f; font-size: 10px; font-weight: 550; line-height: 1.5; }
  .language-picker { display: grid; gap: 12px; margin-bottom: 22px; padding: 20px; border: 1px solid #dce7db; border-radius: 11px; background: #f5f8f2; }
  fieldset { min-width: 0; margin: 0; padding: 0; border: 0; }
  legend { padding: 0; margin: 0 0 12px; color: #415a42; font-size: 12px; font-weight: 650; }
  .target-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .target-choice { display: flex; align-items: center; gap: 8px; min-width: 0; min-height: 43px; padding: 8px 11px; box-sizing: border-box; border: 1px solid #e1e8dc; border-radius: 8px; background: #fff; color: #64765f; font-size: 12px; cursor: pointer; }
  .target-choice.selected { border-color: #a4c2a6; background: #eef5e9; color: #355b36; }
  .target-choice > span { flex-shrink: 0; }
  input[type="checkbox"] { flex-shrink: 0; width: 14px; height: 14px; margin: 0; accent-color: #365e3f; }
  .target-choice small { margin-left: auto; color: #8a9a7e; font-size: 10px; white-space: nowrap; }
  .overwrite-option { display: flex; align-items: center; gap: 7px; margin-top: 16px; color: #667961; font-size: 12px; }
  .picker-help { margin: 10px 0 0; color: #7e8c74; font-size: 11px; line-height: 1.65; }
  .language-picker > .picker-help { margin-top: -5px; }
  .picker-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; margin-top: 2px; }
  .translation-workspace { min-width: 0; }
  .language-tabs { display: flex; gap: 4px; overflow-x: auto; margin: 0 -1px; padding: 0 1px; border-bottom: 1px solid #dce5de; scrollbar-width: thin; }
  .language-tabs button { display: flex; align-items: center; justify-content: center; gap: 6px; position: relative; min-width: 75px; min-height: 43px; padding: 10px 17px; border: 0; border-bottom: 2px solid transparent; border-radius: 7px 7px 0 0; background: transparent; color: #7f8c7a; font-size: 12px; font-weight: 600; white-space: nowrap; }
  .language-tabs button:hover { background: #f5f8f1; color: #426645; }
  .language-tabs button.active { border-bottom-color: #365d3f; background: #f0f5ea; color: #2f5734; }
  .empty-tab-dot { width: 4px; height: 4px; border-radius: 50%; background: #a5b18c; }
  .translation-panel { padding-top: 19px; }
  .translation-editor-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
  .translation-editor-heading label { color: #455e3e; font-size: 12px; font-weight: 650; }
  .translated-textarea { min-height: 184px; }
  .translation-empty { display: flex; align-items: center; justify-content: center; gap: 16px; padding: 31px 20px; border: 1px dashed #dce6d7; border-radius: 11px; background: #fafcf7; }
  .empty-icon { display: grid; place-items: center; width: 45px; height: 45px; flex-shrink: 0; border-radius: 13px; background: #edf3e6; color: #6f8d61; }
  .translation-empty strong { color: #5c7454; font-size: 13px; font-weight: 650; }
  .queue-section { background: #fcfdfb; }
  .queue-counts { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
  .queue-counts > span { padding: 4px 7px; border-radius: 5px; background: #f0f3eb; color: #7a8a6e; font-size: 10px; font-weight: 600; white-space: nowrap; }
  .queue-counts > .count-active { background: #e8f1df; color: #4e703d; }
  .queue-counts > .count-error { background: #f8eae3; color: #9e624e; }
  .batch-builder { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; padding: 17px; border: 1px solid #e4eadd; border-radius: 10px; background: #f7f9f3; }
  .batch-builder fieldset { flex: 1; }
  .batch-builder legend { margin-bottom: 10px; color: #6b7d5d; font-size: 11px; }
  .generation-options { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
  .generation-option { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; padding: 6px 9px; box-sizing: border-box; border: 1px solid #e0e7d7; border-radius: 7px; background: #fff; color: #748469; font-size: 11px; cursor: pointer; }
  .generation-option.checked { border-color: #b4c9a2; background: #edf4e5; color: #4f6e3f; }
  .generation-option.empty { color: #a0ab95; background: #f4f6ef; cursor: not-allowed; }
  .generation-option small { color: #93a17d; font-size: 9px; }
  .batch-generate { flex-shrink: 0; }
  .progress-slot { margin-top: 18px; }
  .queue-list { display: grid; gap: 7px; padding: 0; margin: 17px 0 0; list-style: none; }
  .queue-list li { display: flex; align-items: center; gap: 10px; min-height: 53px; padding: 10px 13px; border: 1px solid #e5ebdf; border-radius: 8px; background: #fff; }
  .queue-list li.running { border-color: #cbdbbd; background: #f4f8ed; }
  .queue-list li.failed { border-color: #ecdcd3; background: #fdf8f4; }
  .queue-state-icon { display: grid; place-items: center; width: 27px; height: 27px; flex-shrink: 0; color: #95a581; }
  .running .queue-state-icon { color: #658b48; }
  .failed .queue-state-icon { color: #ba8166; }
  .queue-item-copy { flex: 1; min-width: 0; }
  .queue-item-copy strong { color: #587346; font-size: 12px; font-weight: 650; }
  .queue-item-copy p { margin: 4px 0 0; color: #8e9d7c; font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; }
  .failed .queue-item-copy p { color: #ab8168; }
  .queue-status { flex-shrink: 0; color: #91a17b; font-size: 10px; }
  .running .queue-status { color: #668b48; }
  .failed .queue-status { color: #af7a5d; }
  .queue-item-action { display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0; min-height: 31px; padding: 5px 8px; border: 1px solid #e0e7d6; border-radius: 6px; color: #8e9f73; background: #fff; font-size: 10px; }
  .queue-item-action:hover:not(:disabled) { color: #597638; background: #f4f7ed; }
  .queue-item-action.retry { color: #9f714c; border-color: #e5d7c6; }
  .queue-item-action:disabled { opacity: .5; }
  .queue-empty { display: flex; align-items: center; gap: 9px; padding: 19px 2px 0; color: #a0ad87; }
  .queue-empty > :global(svg) { flex-shrink: 0; }
  .queue-empty p { margin: 0; font-size: 12px; line-height: 1.6; }
  .inline-notice { display: flex; align-items: flex-start; gap: 8px; padding: 13px 16px; border: 1px solid #eadfc9; border-radius: 10px; background: #fbf8ef; color: #8d794b; }
  .inline-notice :global(svg) { flex-shrink: 0; margin-top: 2px; }
  .inline-notice p { margin: 0; font-size: 12px; line-height: 1.6; }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
  :global(.tts-flow .spin) { animation: tts-spin 1s linear infinite; }
  @keyframes tts-spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { :global(.tts-flow .spin) { animation: none; } .script-editor { transition: none; } }
  @media (max-width: 960px) {
    .surface { padding: 20px; }
    .editor-action-row { flex-wrap: wrap; }
    .action-buttons { flex: 1; }
    .batch-builder { align-items: stretch; flex-direction: column; }
    .batch-generate { align-self: flex-end; }
    .save-status { display: none; }
  }
  @media (max-width: 640px) {
    .tts-flow { gap: 16px; }
    .editor-topbar { gap: 9px; }
    .editor-identity { gap: 9px; }
    .back-button { width: 34px; height: 34px; flex-basis: 34px; }
    .title-field input { font-size: 18px; }
    .save-actions .secondary-action { padding: 8px 11px; min-height: 36px; }
    .surface { padding: 17px 15px; border-radius: 12px; }
    .section-heading { align-items: flex-start; flex-wrap: wrap; gap: 13px; margin-bottom: 17px; }
    .section-heading > .secondary-action { margin-left: auto; min-height: 35px; padding: 7px 11px; }
    .heading-copy { gap: 9px; }
    .section-heading h2 { font-size: 15px; }
    .source-language { width: 100%; justify-content: flex-end; font-size: 11px; }
    .source-language select { min-width: 118px; }
    .script-textarea { padding: 15px; min-height: 210px; font-size: 14px; line-height: 1.9; }
    .editor-meta { padding: 9px 13px; font-size: 10px; }
    .editor-action-row { gap: 11px; }
    .action-buttons { flex-wrap: wrap; justify-content: stretch; gap: 7px; }
    .action-buttons > :global(button) { flex: 1 1 135px; padding: 10px 10px; font-size: 12px; }
    .preview-card { grid-template-columns: minmax(0, 1fr); gap: 12px; }
    .preview-card audio { max-width: 100%; }
    .optional-tools summary { font-size: 11px; }
    .language-picker { padding: 14px; margin-bottom: 17px; }
    .target-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .target-choice { gap: 7px; padding: 9px; font-size: 11px; }
    .target-choice small { font-size: 9px; }
    .picker-actions { flex-direction: column; }
    .picker-actions > :global(button) { width: 100%; }
    .language-tabs button { padding: 9px 13px; min-width: 68px; }
    .translation-empty { justify-content: flex-start; gap: 11px; padding: 23px 15px; }
    .empty-icon { width: 38px; height: 38px; border-radius: 10px; }
    .translation-empty strong { font-size: 12px; }
    .batch-builder { padding: 13px; gap: 15px; }
    .batch-generate { width: 100%; }
    .queue-list li { gap: 7px; padding: 10px 8px; }
    .queue-state-icon { width: 22px; }
    .queue-item-copy strong { font-size: 11px; }
    .queue-item-action { padding: 5px 6px; }
    .queue-counts { margin-left: 38px; justify-content: flex-start; }
    .queue-item-copy p { font-size: 10px; }
  }
</style>
