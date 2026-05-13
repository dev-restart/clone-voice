<script lang="ts">
	import { Pause, Play, RotateCcw } from 'lucide-svelte';
	import { formatTime } from '$lib/studio/api';

	let {
		previewUrl,
		timelineTicks,
		trimStart,
		trimEnd,
		ffmpegReady,
		onWaveformElement,
		onPlaySelection,
		onPause,
		onReset
	}: {
		previewUrl: string;
		timelineTicks: number[];
		trimStart: number;
		trimEnd: number;
		ffmpegReady: boolean;
		onWaveformElement: (element: HTMLDivElement) => void;
		onPlaySelection: () => void;
		onPause: () => void;
		onReset: () => void;
	} = $props();

	let waveformEl = $state<HTMLDivElement | null>(null);

	$effect(() => {
		if (waveformEl) onWaveformElement(waveformEl);
	});
</script>

<div class="wave-editor">
	<div bind:this={waveformEl}></div>
	{#if previewUrl && timelineTicks.length}
		<div class="wave-timeline" aria-label="파형 시간 눈금">
			{#each timelineTicks as tick}
				<span>{formatTime(tick)}</span>
			{/each}
		</div>
	{/if}
	{#if !previewUrl}
		<div class="wave-placeholder">음성을 추가하면 파형 편집기가 표시됩니다.</div>
	{/if}
</div>

{#if previewUrl}
	<div class="transport-row">
		<button class="icon-button" onclick={onPlaySelection} aria-label="선택 구간 재생"><Play size={18} /></button>
		<button class="icon-button" onclick={onPause} aria-label="일시 정지"><Pause size={18} /></button>
		<button class="icon-button" onclick={onReset} aria-label="처음으로"><RotateCcw size={18} /></button>
		<span>선택 {formatTime(trimStart)} - {formatTime(trimEnd)} · {Math.max(0, trimEnd - trimStart).toFixed(1)}초</span>
	</div>
{/if}

<details class="sample-rule">
	<summary>저장 규격</summary>
	<span>{ffmpegReady ? '브라우저: 선택 구간 WAV 변환 가능' : '브라우저: 변환 실패 시 원본 업로드'}</span>
	<span>백엔드: 최종 24kHz mono WAV 보정</span>
	<span>STT: 필요 시 16kHz mono WAV 변환</span>
</details>
