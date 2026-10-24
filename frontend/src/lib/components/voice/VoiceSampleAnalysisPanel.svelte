<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
    import HelpPopover from '$lib/components/HelpPopover.svelte';
    import { Loader2, Play, ScanLine, TextSearch } from '@lucide/svelte';
    import { sampleTime, type SampleAnalysis, type SampleCandidate, type TimedTranscript } from '$lib/studio/voice-sample';
    let { analysis, analyzing, analysisError, windowBusy, windowError, transcriptRows, transcriptWindow,
        sttLabel, transcriptProviderLabel, disabled, trimStart, trimEnd, onAnalyze, onChoose, onChooseRegion, onPreview, onTranscribeWindow, onChooseTranscript }:
    {
        analysis: SampleAnalysis | null; analyzing: boolean; analysisError: string;
        windowBusy: boolean; windowError: string; transcriptRows: TimedTranscript[];
        transcriptWindow: { start: number; end: number } | null; sttLabel: string; transcriptProviderLabel: string;
        disabled: boolean; trimStart: number; trimEnd: number;
        onAnalyze: () => void; onChoose: (candidate: SampleCandidate) => void;
        onChooseRegion: (start: number, end: number) => void;
        onPreview: (start: number, end: number) => void; onTranscribeWindow: () => void;
        onChooseTranscript: (row: TimedTranscript) => void;
    } = $props();
    const speechLocations = $derived((analysis?.regions || []).filter((region) => region.kind === 'speech' && region.end - region.start >= .5));
</script>

<section class="sample-analysis" aria-labelledby="sample-analysis-heading">
    <header>
        <div>
            <h3 id="sample-analysis-heading">{t('voice.analysis.title')}</h3>
        </div>
        <button class="secondary-action compact" disabled={disabled || analyzing} onclick={onAnalyze} type="button">
            {#if analyzing}<Loader2 size={16} class="spin" />{t('voice.analysis.busy')}{:else}<ScanLine size={16} />{analysis ? t('voice.analysis.again') : t('voice.analysis.run')}{/if}
        </button>
    </header>
    {#if analyzing}<p class="sample-status" role="status">{t('voice.analysis.working')}</p>{/if}
    {#if analysisError}<p class="sample-error" role="alert">{analysisError}</p>{/if}
    {#if analysis}
        <p class="sample-status">{analysis.message}</p>
        {#if speechLocations.length}
            <div class="speech-locations">
                <strong>{t('voice.analysis.found')}</strong>
                <div>
                    {#each speechLocations.slice(0, 24) as region}
                        <button type="button" class="secondary-action compact" disabled={disabled}
                            onclick={() => onChooseRegion(region.start, region.end)}
                            aria-label={t('voice.analysis.pickRegion', { time: sampleTime(region.start) })}>
                            {sampleTime(region.start)}–{sampleTime(region.end)}
                        </button>
                    {/each}
                </div>
                {#if speechLocations.length > 24}<p>{t('voice.analysis.first24')}</p>{/if}
            </div>
        {/if}
        {#if analysis.candidates.length}
            <div class="candidate-list">
                {#each analysis.candidates as candidate}
                    <article class:chosen={Math.abs(trimStart - candidate.start) < .05 && Math.abs(trimEnd - candidate.end) < .05}>
                        <div class="candidate-title"><strong>{candidate.label}</strong><span>{sampleTime(candidate.start)}–{sampleTime(candidate.end)} · {t('voice.analysis.seconds', { seconds: (candidate.end - candidate.start).toFixed(1) })}</span></div>
                        <p>{candidate.reasons.join(' · ')}</p>
                        <div class="candidate-actions">
                            <button type="button" class="secondary-action compact" disabled={disabled} onclick={() => onPreview(candidate.start, candidate.end)} aria-label={candidate.label + ' ' + t('voice.analysis.preview')}><Play size={14} />{t('voice.analysis.preview')}</button>
                            <button type="button" class="secondary-action compact" disabled={disabled} onclick={() => onChoose(candidate)} aria-label={candidate.label + ' ' + t('voice.analysis.chooseLabel')}>{t('voice.analysis.choose')}</button>
                        </div>
                    </article>
                {/each}
            </div>
        {:else}
            <p class="sample-empty">{t('voice.analysis.none')}</p>
        {/if}
        {#each analysis.warnings as warning}<p class="sample-note">{warning}</p>{/each}
    {/if}
    <div class="transcript-explorer">
        <header>
            <div class="flex items-center gap-1"><h3>{t('voice.window.title')}</h3><HelpPopover label={t('voice.window.title')} text={t('voice.window.help', { engine: sttLabel })} /></div>
            <button class="secondary-action compact" type="button" disabled={disabled || windowBusy} onclick={onTranscribeWindow}>
                {#if windowBusy}<Loader2 size={16} class="spin" />{t('voice.window.busy')}{:else}<TextSearch size={16} />{t('voice.window.run')}{/if}
            </button>
        </header>
        {#if windowError}<p class="sample-error" role="alert">{windowError}</p>{/if}
        {#if transcriptWindow}
            <p class="sample-status">{t('voice.window.range', { range: sampleTime(transcriptWindow.start) + '–' + sampleTime(transcriptWindow.end) })} · {transcriptProviderLabel}</p>
            {#if !transcriptRows.length && !windowBusy}<p class="sample-empty">{t('voice.window.empty')}</p>{/if}
            <div class="transcript-rows">
                {#each transcriptRows as row}
                    <div class="transcript-row">
                        <button type="button" class="transcript-select" disabled={disabled} onclick={() => onChooseTranscript(row)} aria-label={t('voice.window.pickLabel', { time: sampleTime(row.start) })}>
                            <time>{sampleTime(row.start)}–{sampleTime(row.end)}</time><span>{row.text}</span>
                        </button>
                        <button class="icon-button" type="button" disabled={disabled} onclick={() => onPreview(row.start, row.end)} aria-label={t('voice.window.previewLabel', { time: sampleTime(row.start) })}><Play size={16} /></button>
                    </div>
                {/each}
            </div>
        {/if}
    </div>
</section>

<style>
    .sample-analysis { display: grid; gap: 12px; border: 1px solid #d4dfdb; border-radius: 8px; padding: 18px; background: #fff; color: #26332e; word-break: keep-all; overflow-wrap: anywhere; }
    header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
    header > div { flex: 1 1 250px; }
    h3 { margin: 0; font-size: 14px; font-weight: 680; }
    p { margin: 6px 0 0; color: #60706a; font-size: 12px; line-height: 1.65; }
    .sample-status { color: #476252; }
    .sample-error { color: #9b3630; background: #fff5f3; border-radius: 6px; padding: 10px; }
    .sample-note { font-size: 11px; }
    .sample-empty { background: #f4f7f5; padding: 12px; border-radius: 6px; }
    .speech-locations { padding: 12px; border-radius: 7px; background: #f2f8f5; }
    .speech-locations strong { font-size: 12px; }
    .speech-locations > div { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
    .candidate-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
    article { min-width: 0; border: 1px solid #d9e3df; border-radius: 7px; padding: 13px; }
    article.chosen { border-color: #168a75; background: #f0f8f4; }
    .candidate-title { display: flex; flex-direction: column; gap: 5px; font-size: 12px; }
    .candidate-title span { color: #60706a; font-size: 11px; font-variant-numeric: tabular-nums; }
    .candidate-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; }
    .transcript-explorer { border-top: 1px solid #e0e7e3; padding-top: 16px; margin-top: 4px; }
    .transcript-rows { display: grid; gap: 5px; max-height: 300px; overflow-y: auto; margin-top: 10px; }
    .transcript-row { display: flex; align-items: center; gap: 6px; border: 1px solid #e0e7e3; border-radius: 6px; padding-right: 6px; }
    .transcript-select { flex: 1; min-width: 0; display: grid; grid-template-columns: 125px minmax(0, 1fr); align-items: start; gap: 8px; border: 0; background: transparent; padding: 10px; color: #26332e; font-size: 12px; line-height: 1.6; text-align: left; }
    .transcript-select:hover { background: #f0f8f4; }
    time { font-size: 11px; color: #60706a; font-variant-numeric: tabular-nums; }
    @media (max-width: 900px) { .candidate-list { grid-template-columns: 1fr; } }
    @media (max-width: 600px) { .sample-analysis { padding: 13px; } .transcript-select { grid-template-columns: 1fr; } header > button { width: 100%; justify-content: center; } }
</style>
