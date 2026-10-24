<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	let {
		progress,
		fallbackMessage = ''
	}: {
		progress: { percent: number; message: string; elapsed: number; active: boolean };
		fallbackMessage?: string;
	} = $props();
</script>

{#if progress.active || progress.message}
	<div class="generation-progress" aria-live="polite">
		<div>
			<strong>{progress.message || fallbackMessage || t('queue.working')}</strong>
			<span>{progress.percent}% · {progress.elapsed}s</span>
		</div>
		<meter min="0" max="100" value={progress.percent}></meter>
	</div>
{/if}
