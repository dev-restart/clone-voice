<script lang="ts">
	import { Download, Wand2 } from 'lucide-svelte';
	import { audioUrl } from '$lib/studio/api';
	import type { VoiceConversionJob, VoiceProfile } from '$lib/studio/types';

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
			<h3>버전별 변환 결과</h3>
			<p>이 작업에서 생성한 결과를 버전별로 재생합니다.</p>
		</div>
		<span class="soft-badge">{projectVersions.length}개</span>
	</div>
	<div class="result-list">
		{#each projectVersions as item, index (item.id)}
			<article class="result-row vc-history-row">
				<div>
					<strong>v{projectVersions.length - index} · {voices.find((voice) => voice.id === item.target_voice_id)?.name ?? '대상 목소리'} · {item.model_id}</strong>
					<small>{new Date(item.created_at).toLocaleString('ko-KR')}</small>
					{#if item.transcript}<p>{item.transcript}</p>{/if}
				</div>
				<audio controls src={audioUrl(item.output_audio_url)}></audio>
				<a class="icon-button" href={audioUrl(item.output_audio_url)} download aria-label={`v${projectVersions.length - index} 변환 결과 다운로드`}><Download size={17} /></a>
			</article>
		{:else}
			<p class="field-helper">아직 이 작업에서 생성한 변환 결과가 없습니다.</p>
		{/each}
	</div>
</div>
