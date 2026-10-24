<script lang="ts">
	import { Languages } from '@lucide/svelte';
	import * as ToggleGroup from '$lib/components/ui/toggle-group';
	import { LOCALES, i18n, t, type Locale } from '$lib/i18n/index.svelte';

	let { class: className = '' }: { class?: string } = $props();
</script>

<div class="flex items-center gap-1.5 {className}" role="group" aria-label={t('language.switch')}>
	<Languages size={16} class="text-muted-foreground" aria-hidden="true" />
	<ToggleGroup.Root
		type="single"
		variant="outline"
		size="sm"
		value={i18n.locale}
		onValueChange={(next) => { if (next) i18n.set(next as Locale); }}
	>
		{#each LOCALES as item (item.code)}
			<ToggleGroup.Item value={item.code} aria-label={item.label} lang={item.code} class="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground">{item.label}</ToggleGroup.Item>
		{/each}
	</ToggleGroup.Root>
</div>
