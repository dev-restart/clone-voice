<script lang="ts">
	import { Download, Loader2 } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';
	import { t } from '$lib/i18n/index.svelte';
	import { downloadAudio, type AudioDownloadFormat } from '$lib/studio/download';

	let { path, filename, label = '' }: {
		path: string;
		filename: string;
		label?: string;
	} = $props();

	const name = $derived(label || t('download.audio'));
	let format = $state<AudioDownloadFormat>('mp3');
	let downloading = $state(false);
	let downloadError = $state('');

	async function download() {
		if (downloading) return;
		downloading = true;
		downloadError = '';
		try {
			await downloadAudio(path, filename, format);
		} catch (error) {
			downloadError = error instanceof Error ? error.message : String(error);
		} finally {
			downloading = false;
		}
	}
</script>

<div class="min-w-0 max-w-full">
	<div class="flex flex-wrap items-center gap-1.5">
		<select class="studio-input min-h-9 w-auto min-w-[70px] px-2.5 py-1.5 text-xs" aria-label={t('download.formatLabel', { name })} bind:value={format} disabled={downloading}>
			<option value="mp3">MP3</option>
			<option value="wav">WAV</option>
		</select>
		<Button variant="secondary" onclick={download} disabled={downloading} aria-busy={downloading} aria-label={t('download.action', { name, format: format.toUpperCase() })}>
			{#if downloading}<Loader2 size={16} class="animate-spin" aria-hidden="true" />{:else}<Download size={16} aria-hidden="true" />{/if}
			{downloading ? t('tts.results.preparing') : t('tts.results.download', { format: format.toUpperCase() })}
		</Button>
	</div>
	{#if downloadError}<p role="alert" class="text-danger mt-2 max-w-72 text-xs break-words">{downloadError}</p>{/if}
</div>
