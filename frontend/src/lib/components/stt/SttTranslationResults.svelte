<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import { languages } from '$lib/studio/api';

	let { translations }: { translations: Record<string, string> } = $props();
	let entries = $derived(Object.entries(translations));
</script>

<div class="translation-stack">
	{#each entries as [code, value]}
		<article><strong>{languages.find((item) => item.code === code)?.label ?? code}</strong><p>{value}</p></article>
	{:else}
		<article class="translation-empty">
			<strong>{t('stt.translations')}</strong>
		</article>
	{/each}
</div>
