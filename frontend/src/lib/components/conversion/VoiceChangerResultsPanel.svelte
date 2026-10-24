<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { audioUrl } from '$lib/studio/api';
	import type { VoiceConversionJob, VoiceProfile } from '$lib/studio/types';
	import AudioDownload from '../AudioDownload.svelte';

	let {
		projectVersions,
		voices
	}: {
		projectVersions: VoiceConversionJob[];
		voices: VoiceProfile[];
	} = $props();
</script>

<div class="result-preview">
	<div class="section-heading compact-heading">
		<div>
			<h3>{t('cover.results.title')}</h3>
		</div>
		<span class="soft-badge">{t('home.count', { count: projectVersions.length })}</span>
	</div>
	<div class="result-list">
		{#each projectVersions as item, index (item.id)}
			<article class="result-row vc-history-row">
				<div>
					<strong>v{projectVersions.length - index} · {voices.find((voice) => voice.id === item.target_voice_id)?.name ?? t('cover.results.target')}</strong>
					<small>{new Date(item.created_at).toLocaleString('ko-KR')}</small>
					{#if item.transcript}<p>{item.transcript}</p>{/if}
				</div>
				<audio controls preload="none" src={audioUrl(item.output_audio_url)} aria-label={t('cover.results.listen', { n: projectVersions.length - index })}></audio>
				<AudioDownload path={item.output_audio_url} filename={`cover-v${projectVersions.length - index}-${item.id.slice(0, 8)}`} label={t('cover.results.name', { n: projectVersions.length - index })} />
			</article>
		{:else}
			<p class="field-helper">{t('cover.results.empty')}</p>
		{/each}
	</div>
</div>
