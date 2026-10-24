<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { Download, Loader2, Play, Trash2, Wand2 } from '@lucide/svelte';
	import { audioUrl, formatDate, formatTime, languages } from '$lib/studio/api';
	import type { ContentItem, ContentResult } from '$lib/studio/types';
	import AudioDownload from '../AudioDownload.svelte';
	import HelpPopover from '../HelpPopover.svelte';

	let {
		results,
		scripts = {},
		busy = false,
		deletingResultId = '',
		exportingResultId = '',
		onExport,
		onDeleteResult,
		onGenerateAgain
	}: {
		results: ContentItem['results'];
		scripts?: Record<string, string>;
		busy?: boolean;
		deletingResultId?: string;
		exportingResultId?: string;
		onExport?: (result: ContentResult, format: 'wav' | 'mp3' | 'zip' | 'txt') => void;
		onDeleteResult?: (result: ContentResult) => void;
		onGenerateAgain?: (result: ContentResult) => void;
	} = $props();
	let exportFormat = $state<'wav' | 'mp3' | 'zip' | 'txt'>('mp3');
</script>

<section class="surface tts-results-panel">
	<div class="section-heading">
		<div>
			<h2>{t('tts.results.title')}</h2>
		</div>
		<span class="soft-badge">{t('home.count', { count: results.length })}</span>
		{#if results.length && onExport}<div class="export-format-field"><label class="tts-export-format">{t('tts.results.format')}<select class="studio-input" aria-label={t('tts.results.format')} bind:value={exportFormat} disabled={Boolean(exportingResultId)}><option value="mp3">MP3</option><option value="wav">{t('tts.results.fmt.wav')}</option><option value="zip">{t('tts.results.fmt.zip')}</option><option value="txt">{t('tts.results.fmt.txt')}</option></select></label><HelpPopover label={t('tts.results.fmt.zip')} text={t('tts.results.zipHelp')} /></div>{/if}
	</div>
	{#if results.some((result) => !result.production_settings)}<p class="legacy-result-note">{t('tts.results.legacy')}</p>{/if}
	<div class="result-list">
		{#each results as result (result.id)}
			<article class="result-row tts-result-row">
				<div class="result-copy">
					<strong>{languages.find((item) => item.code === result.language)?.label ?? result.language}</strong>
					<small>{result.voice_name ?? t('ttsws.defaultVoice')} · {formatTime(result.duration_seconds)} · {formatDate(result.created_at)}</small>
					{#if scripts[result.language] !== undefined && scripts[result.language].trim() !== result.text.trim()}<span class="result-stale">{t('tts.results.stale')}</span>{/if}
					<p>{result.text}</p>
					{#if result.spoken_text && result.spoken_text !== result.text}<details class="result-pronunciation"><summary>{t('tts.results.spoken')}</summary><p>{result.spoken_text}</p></details>{/if}
				</div>
				<audio controls preload="none" aria-label={t('tts.results.audioLabel', { voice: result.voice_name ?? t('ttsws.defaultVoice') })} src={audioUrl(result.audio_url)}></audio>
				<div class="result-actions">
					{#if onGenerateAgain}
						<button class="icon-button" disabled={busy} aria-label={t('tts.results.again')} onclick={() => onGenerateAgain?.(result)}><Play size={17} /></button>
					{/if}
					{#if onExport}<button class="secondary-action" disabled={Boolean(exportingResultId)} onclick={() => onExport?.(result, exportFormat)} aria-label={t('tts.results.download', { format: exportFormat.toUpperCase() })}>{#if exportingResultId === result.id}<Loader2 size={17} class="spin" />{:else}<Download size={17} />{/if}{exportingResultId === result.id ? t('tts.results.preparing') : t('tts.results.download', { format: exportFormat.toUpperCase() })}</button>{:else}<AudioDownload path={result.audio_url} filename={`tts-${result.language}-${result.id.slice(0, 8)}`} label={t('tts.results.audioName')} />{/if}
					{#if onDeleteResult}
						<button class="icon-button danger" disabled={busy || deletingResultId === result.id} aria-label={t('tts.results.delete')} title={t('tts.results.deleteTitle')} onclick={() => onDeleteResult?.(result)}><Trash2 size={17} /></button>
					{/if}
				</div>
			</article>
		{:else}
			<div class="empty-state small"><Wand2 size={44} /><p>{t('tts.results.empty')}</p></div>
		{/each}
	</div>
</section>
<style>
	.export-format-field { display: flex; align-items: end; gap: 8px; margin-left: auto; }
	.result-stale { display: inline-block; color: var(--warning); background: var(--warning-soft); padding: 3px 8px; border-radius: 5px; font-size: 12px; margin: 7px 0; }
	@media (max-width: 760px) { .export-format-field { width: 100%; margin-left: 0; } }
</style>
