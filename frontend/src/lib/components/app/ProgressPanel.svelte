<script lang="ts">
	let {
		progress,
		fallbackMessage = '작업 중입니다.'
	}: {
		progress: { percent: number; message: string; elapsed: number; active: boolean };
		fallbackMessage?: string;
	} = $props();
</script>

{#if progress.active || progress.message}
	<div class="generation-progress" aria-live="polite">
		<div>
			<strong>{progress.message || fallbackMessage}</strong>
			<span>{progress.percent}% · {progress.elapsed}s</span>
		</div>
		<meter min="0" max="100" value={progress.percent}></meter>
	</div>
{/if}
