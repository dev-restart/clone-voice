<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { Download, Loader2, Volume2 } from '@lucide/svelte';
	import { apiFetch, audioUrl, formatTime } from '$lib/studio/api';
	import type { StoryStudioResult } from '$lib/studio/types';
	import { downloadResponse } from '$lib/studio/download';

	let { result, projectId, stale = false, onNotice }: {
		result: StoryStudioResult | null;
		projectId: string;
		stale?: boolean;
		onNotice: (type: 'success' | 'error' | 'info', text: string) => void;
	} = $props();
	let player = $state<HTMLAudioElement | null>(null);
	let exporting = $state('');
	let audioError = $state(false);
	let previousUrl = '';
	const exportOptions = $derived<Array<{ format: 'mp3' | 'wav' | 'txt' | 'srt' | 'zip'; label: string }>>([
		{ format: 'mp3', label: 'MP3' },
		{ format: 'wav', label: 'WAV' },
		{ format: 'txt', label: t('story.player.txt') },
		{ format: 'srt', label: t('story.player.srt') },
		{ format: 'zip', label: t('story.player.zip') }
	]);
	$effect(() => {
		if (result?.audio_url !== previousUrl) { previousUrl = result?.audio_url ?? ''; audioError = false; }
	});
	let timeline = $derived.by(() => {
		let offset = 0;
		return (result?.segments ?? []).map((segment) => {
			const start = offset;
			offset += (segment.duration_seconds ?? 0) + segment.pause_after_ms / 1000;
			return { ...segment, start };
		});
	});

	function seek(seconds: number) {
		if (!player) return;
		player.currentTime = seconds;
		void player.play().catch(() => onNotice('info', t('story.player.pressPlay')));
	}

	async function exportResult(format: 'mp3' | 'wav' | 'txt' | 'srt' | 'zip') {
		if (exporting) return;
		exporting = format;
		try {
			const response = await apiFetch(`/api/story-studio/projects/${encodeURIComponent(projectId)}/export?format=${format}`);
			await downloadResponse(response, `${(result?.title || 'dialogue').replace(/[\\/:*?"<>|]/g, '_')}.${format}`);
		} catch (error) { onNotice('error', error instanceof Error ? error.message : String(error)); }
		finally { exporting = ''; }
	}
</script>

{#if result}
	<section class="story-player surface" aria-label={t('story.player.region')}>
		<div class="story-player-heading">
			<Volume2 size={19} /><strong>{result.title}</strong><span>{formatTime(result.duration_seconds)}</span>
			<span class="story-ai-label">{t('story.player.ai')}</span>
		</div>
		{#if stale}<p class="story-result-warning" role="status">{t('story.player.stale')}</p>{/if}
		{#if !result.source_segments}<p class="field-helper">{t('story.player.legacy')}</p>{/if}
		{#if audioError}<p class="story-result-warning" role="alert">{t('story.player.audioError')}</p>{/if}
		<audio bind:this={player} controls preload="metadata" src={audioUrl(result.audio_url)} aria-label={t('story.player.listen', { title: result.title })} onerror={() => audioError = true}></audio>
		<div class="story-timeline" aria-label={t('story.player.timeline')}>
			{#each timeline as segment (segment.id)}
				<button style={`flex-grow: ${Math.max(1, Math.round((segment.duration_seconds ?? 1) * 10))}`} onclick={() => seek(segment.start)} aria-label={t('story.player.play', { n: segment.index })} title={segment.text}>
					{segment.index}. {segment.speaker_name || segment.voice_name || t('story.speaker')} <small>{formatTime(segment.start)}</small>
				</button>
			{/each}
		</div>
		<div class="story-export-actions" aria-label={t('story.player.export')}>
			{#each exportOptions as option (option.format)}
				<button class="secondary-action compact" disabled={Boolean(exporting)} aria-busy={exporting === option.format} onclick={() => exportResult(option.format)}>
					{#if exporting === option.format}<Loader2 class="spin" size={15} />{:else}<Download size={15} />{/if}{exporting === option.format ? t('tts.results.preparing') : option.label}
				</button>
			{/each}
		</div>
	</section>
{/if}
