<script lang="ts">
	import { languages } from '$lib/studio/api';

	let { translations }: { translations: Record<string, string> } = $props();
	let entries = $derived(Object.entries(translations));
</script>

<div class="translation-stack">
	{#each entries as [code, value]}
		<article><strong>{languages.find((item) => item.code === code)?.label ?? code}</strong><p>{value}</p></article>
	{:else}
		<article class="translation-empty">
			<strong>번역 결과</strong>
			<p>텍스트 변환 후 오른쪽에서 언어를 선택하면 번역 결과가 여기에 쌓입니다.</p>
		</article>
	{/each}
</div>
