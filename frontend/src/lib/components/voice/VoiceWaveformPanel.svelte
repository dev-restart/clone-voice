<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
    import HelpPopover from '$lib/components/HelpPopover.svelte';
    import { Pause, Play, RotateCcw, ZoomIn, ZoomOut, Focus } from '@lucide/svelte';
    import { formatTime } from '$lib/studio/api';
    import { sampleTime, type SampleRegion, type SampleRegionKind } from '$lib/studio/voice-sample';
    let { previewUrl, timelineTicks, trimStart, trimEnd, duration, currentTime, overviewPeaks, audioRegions,
        viewStart, viewEnd, disabled, onWaveformElement, onPlaySelection, onPause, onReset,
        onChangeRange, onSeekTime, onZoomIn, onZoomOut, onFocusSelection, onShowAll }:
    {
        previewUrl: string; timelineTicks: number[]; trimStart: number; trimEnd: number;
        duration: number; currentTime: number; overviewPeaks: number[]; audioRegions: SampleRegion[];
        viewStart: number; viewEnd: number; disabled: boolean;
        onWaveformElement: (element: HTMLDivElement) => void; onPlaySelection: () => void;
        onPause: () => void; onReset: () => void; onChangeRange: (start: number, end: number) => void;
        onSeekTime: (time: number) => void; onZoomIn: () => void; onZoomOut: () => void;
        onFocusSelection: () => void; onShowAll: () => void;
    } = $props();
    let waveformEl = $state<HTMLDivElement | null>(null);
    const colors: Record<SampleRegionKind, string> = { speech: '#59b7a4', mixed: '#d4b564', music: '#bdafd7', singing: '#a98ace', sound: '#becbc5', silence: '#eef2ef' };
    let overviewPath = $derived(overviewPeaks.map((peak, index) => {
        const x = (index + .5) / Math.max(1, overviewPeaks.length) * 800;
        const height = Math.max(1, Math.sqrt(peak) * 21);
        return 'M' + x.toFixed(1) + ',' + (26 - height).toFixed(1) + 'V' + (26 + height).toFixed(1);
    }).join(' '));
    $effect(() => { if (waveformEl) onWaveformElement(waveformEl); });
    function seekOverview(event: MouseEvent) {
        if (disabled || !duration || event.detail === 0) return;
        const rect = event.currentTarget instanceof HTMLElement ? event.currentTarget.getBoundingClientRect() : null;
        if (rect) onSeekTime(Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * duration);
    }
    function keyOverview(event: KeyboardEvent) {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault();
            onSeekTime(currentTime + (event.key === 'ArrowRight' ? 1 : -1) * (event.shiftKey ? 30 : 5));
        }
    }
</script>

<section class="sample-waveform" aria-labelledby="sample-waveform-heading">
    <header><div class="flex items-center gap-1"><h3 id="sample-waveform-heading">{t('voice.wave.title')}</h3><HelpPopover label={t('voice.wave.title')} text={t('voice.wave.help')} /></div>{#if duration}<span class="total-duration">{t('voice.wave.total', { time: formatTime(duration) })}</span>{/if}</header>
    {#if previewUrl && duration}
        <div class="overview-heading"><strong>{t('voice.wave.overview')}</strong></div>
        <button class="overview" type="button" onclick={seekOverview} onkeydown={keyOverview} disabled={disabled} aria-label={t('voice.wave.seek')}>
            <svg viewBox="0 0 800 52" preserveAspectRatio="none" aria-hidden="true">
                {#each audioRegions as region}
                    <rect x={region.start / duration * 800} y="0" width={Math.max(.5, (region.end - region.start) / duration * 800)} height="52" fill={colors[region.kind]} opacity=".45" />
                {/each}
                <path d={overviewPath} stroke="#668d81" stroke-width="1.5" fill="none" />
                <rect x={viewStart / duration * 800} y="1" width={Math.max(2, (viewEnd - viewStart) / duration * 800)} height="50" fill="#168a75" opacity=".08" stroke="#168a75" />
                <rect x={trimStart / duration * 800} y="1" width={Math.max(2, (trimEnd - trimStart) / duration * 800)} height="50" fill="#117961" opacity=".4" />
                <line x1={currentTime / duration * 800} x2={currentTime / duration * 800} y1="0" y2="52" stroke="#192821" stroke-width="1.5" />
            </svg>
        </button>
        <div class="overview-labels"><span>0:00</span><span>{formatTime(duration)}</span></div>
        {#if audioRegions.length}
            <div class="sound-legend"><span><i style="background:#59b7a4"></i>{t('voice.legend.speech')}</span><span><i style="background:#d4b564"></i>{t('voice.legend.mixed')}</span><span><i style="background:#a98ace"></i>{t('voice.legend.music')}</span><span><i style="background:#becbc5"></i>{t('voice.legend.other')}</span></div>
        {/if}
        <div class="zoom-toolbar">
            <span>{t('voice.wave.view', { range: sampleTime(viewStart) + '–' + sampleTime(viewEnd) })}</span>
            <div>
                <button class="secondary-action compact" type="button" disabled={disabled} onclick={onZoomOut} aria-label={t('voice.wave.zoomOut')}><ZoomOut size={15} /></button>
                <button class="secondary-action compact" type="button" disabled={disabled} onclick={onZoomIn} aria-label={t('voice.wave.zoomIn')}><ZoomIn size={15} /></button>
                <button class="secondary-action compact" type="button" disabled={disabled} onclick={onFocusSelection}><Focus size={15} />{t('voice.wave.zoomSelection')}</button>
                <button class="secondary-action compact" type="button" disabled={disabled} onclick={onShowAll}>{t('home.recent.all')}</button>
            </div>
        </div>
    {/if}
    <div class="wave-editor">
        <div bind:this={waveformEl}></div>
        {#if previewUrl && timelineTicks.length}
            <div class="wave-timeline" aria-label={t('voice.wave.ticks')}>{#each timelineTicks as tick}<span>{formatTime(tick)}</span>{/each}</div>
        {/if}
        {#if !previewUrl}<div class="wave-placeholder">{t('voice.wave.placeholder')}</div>{/if}
    </div>
    {#if previewUrl && duration}
        <div class="sample-transport">
            <div class="play-controls">
                <button class="secondary-action compact" type="button" disabled={disabled} onclick={onPlaySelection} aria-label={t('voice.wave.playLabel')}><Play size={16} />{t('voice.wave.play')}</button>
                <button class="icon-button" type="button" onclick={onPause} aria-label={t('voice.wave.pause')}><Pause size={18} /></button>
                <button class="icon-button" type="button" disabled={disabled} onclick={onReset} aria-label={t('voice.wave.restart')}><RotateCcw size={18} /></button>
                <span>{t('voice.wave.position', { time: sampleTime(currentTime) })}</span>
            </div>
            <div class="range-inputs">
                <label>{t('voice.wave.startSec')}<input type="number" min="0" max={duration} step="0.1" value={Number(trimStart.toFixed(3))} disabled={disabled} onchange={(event) => onChangeRange(event.currentTarget.valueAsNumber, trimEnd)} aria-label={t('voice.wave.startLabel')} /></label>
                <label>{t('voice.wave.endSec')}<input type="number" min="0" max={duration} step="0.1" value={Number(trimEnd.toFixed(3))} disabled={disabled} onchange={(event) => onChangeRange(trimStart, event.currentTarget.valueAsNumber)} aria-label={t('voice.wave.endLabel')} /></label>
                <strong>{t('voice.wave.selected', { seconds: (trimEnd - trimStart).toFixed(1) })}</strong>
            </div>
        </div>
        <p class="selection-summary" role="status">{t('voice.wave.summary', { range: sampleTime(trimStart) + '–' + sampleTime(trimEnd) })}</p>
    {/if}
</section>

<style>
    .sample-waveform { display: grid; gap: 10px; min-width: 0; word-break: keep-all; }
    header { display: flex; justify-content: space-between; align-items: start; gap: 15px; }
    h3 { margin: 0; color: #26332e; font-size: 15px; }
    p { margin: 6px 0 0; color: #60706a; font-size: 12px; line-height: 1.6; }
    .total-duration { flex-shrink: 0; font-size: 12px; color: #60706a; }
    .overview-heading { display: flex; align-items: center; gap: 12px; justify-content: space-between; font-size: 11px; color: #60706a; flex-wrap: wrap; }
    .overview-heading strong { color: #344c41; font-size: 12px; }
    .overview { display: block; width: 100%; height: 60px; padding: 4px 0; overflow: hidden; border: 1px solid #cbdad3; border-radius: 6px; background: #f6f9f7; cursor: crosshair; }
    .overview svg { display: block; width: 100%; height: 52px; }
    .overview:focus-visible { outline: 2px solid #168a75; outline-offset: 3px; }
    .overview-labels, .zoom-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 10px; color: #60706a; font-size: 11px; font-variant-numeric: tabular-nums; }
    .zoom-toolbar { flex-wrap: wrap; margin-top: 5px; }
    .zoom-toolbar > div { display: flex; flex-wrap: wrap; gap: 5px; }
    .sound-legend { display: flex; flex-wrap: wrap; gap: 12px; color: #60706a; font-size: 11px; }
    .sound-legend span { display: inline-flex; align-items: center; gap: 4px; }
    i { width: 9px; height: 9px; border-radius: 2px; }
    .wave-editor { min-width: 0; overflow: hidden; }
    .sample-transport { display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap; }
    .play-controls { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; }
    .play-controls > span { color: #60706a; font-size: 11px; font-variant-numeric: tabular-nums; }
    .range-inputs { display: flex; align-items: end; gap: 10px; flex-wrap: wrap; }
    .range-inputs label { display: grid; gap: 4px; font-size: 11px; color: #60706a; }
    .range-inputs input { width: 110px; max-width: 100%; border: 1px solid #cbdad3; border-radius: 5px; padding: 7px 8px; color: #26332e; font-size: 12px; font-variant-numeric: tabular-nums; background: white; }
    .range-inputs strong { padding-bottom: 8px; color: #344c41; font-size: 12px; }
    .selection-summary { margin: 0; }
    @media (max-width: 600px) { .range-inputs { width: 100%; } .range-inputs input { width: 100px; } }
</style>
