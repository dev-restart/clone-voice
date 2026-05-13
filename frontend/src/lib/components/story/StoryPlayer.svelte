<script lang="ts">
	import { Download, Volume2 } from 'lucide-svelte';
	import { audioUrl, formatTime } from '$lib/studio/api';
	import type { StoryStudioResult } from '$lib/studio/types';

	let { result }: { result: StoryStudioResult | null } = $props();
</script>

{#if result}
	<section class="story-player surface">
		<div>
			<Volume2 size={19} />
			<strong>{result.title}</strong>
			<span>{formatTime(result.duration_seconds)}</span>
			<a class="icon-button" href={audioUrl(result.audio_url)} download aria-label="스토리북 오디오 다운로드"><Download size={17} /></a>
		</div>
		<audio controls src={audioUrl(result.audio_url)}></audio>
		<div class="story-timeline">
			{#each result.segments as segment (segment.id)}
				<span style={`flex-grow: ${Math.max(1, Math.round((segment.duration_seconds ?? 1) * 10))}`}>
					{segment.index}. {segment.voice_name ?? 'Auto'} · {segment.language}
				</span>
			{/each}
		</div>
	</section>
{/if}
