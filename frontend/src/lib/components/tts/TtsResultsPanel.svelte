<script lang="ts">
	import { Download, Play, Trash2, Wand2 } from 'lucide-svelte';
	import { audioUrl, formatDate, formatTime, languages } from '$lib/studio/api';
	import type { ContentItem, ContentResult } from '$lib/studio/types';

	let {
		results,
		busy = false,
		deletingResultId = '',
		onDeleteResult,
		onGenerateAgain
	}: {
		results: ContentItem['results'];
		busy?: boolean;
		deletingResultId?: string;
		onDeleteResult?: (result: ContentResult) => void;
		onGenerateAgain?: (result: ContentResult) => void;
	} = $props();
</script>

<section class="surface tts-results-panel">
	<div class="section-heading">
		<div>
			<h2>생성 결과</h2>
			<p>이 콘텐츠에서 만든 음성을 재생하고 다운로드하거나 같은 문장으로 다시 생성할 수 있습니다.</p>
		</div>
		<span class="soft-badge">{results.length}개</span>
	</div>
	<div class="result-list">
		{#each results as result}
			<article class="result-row tts-result-row">
				<div class="result-copy">
					<strong>{languages.find((item) => item.code === result.language)?.label ?? result.language} · {result.model_id ?? 'TTS'}</strong>
					<small>{result.voice_name ?? '기본 목소리'} · {formatTime(result.duration_seconds)} · {formatDate(result.created_at)}</small>
					<p>{result.text}</p>
				</div>
				<audio controls src={audioUrl(result.audio_url)}></audio>
				<div class="result-actions">
					{#if onGenerateAgain}
						<button class="icon-button" disabled={busy} aria-label="같은 문장으로 다시 생성" onclick={() => onGenerateAgain?.(result)}><Play size={17} /></button>
					{/if}
					<a class="icon-button" href={audioUrl(result.audio_url)} download aria-label="다운로드"><Download size={17} /></a>
					{#if onDeleteResult}
						<button class="icon-button danger" disabled={busy || deletingResultId === result.id} aria-label="생성 결과 삭제" title="이 생성 결과 삭제" onclick={() => onDeleteResult?.(result)}><Trash2 size={17} /></button>
					{/if}
				</div>
			</article>
		{:else}
			<div class="empty-state small"><Wand2 size={44} /><p>아직 생성된 음성이 없습니다. 대본을 입력하고 음성 생성을 실행하세요.</p></div>
		{/each}
	</div>
</section>
