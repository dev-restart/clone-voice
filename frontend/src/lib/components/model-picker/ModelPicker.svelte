<script lang="ts">
	import * as Select from '$lib/components/ui/select';
	import { t } from '$lib/i18n/index.svelte';
	import { domainMeta } from '$lib/studio/model-domains';
	import type { ModelDomain, RuntimeModelStatus } from '$lib/studio/types';

	// One picker for every workspace: voice, music, cover and sound-effect models share the same control.
	let {
		models,
		value = '',
		domain = 'voice',
		disabled = false,
		id,
		class: className = '',
		onChange
	}: {
		models: RuntimeModelStatus[];
		value?: string;
		domain?: ModelDomain;
		disabled?: boolean;
		id?: string;
		class?: string;
		onChange: (modelId: string) => void;
	} = $props();

	const selected = $derived(models.find((model) => model.id === value));
</script>

<Select.Root type="single" {value} {disabled} onValueChange={(next) => next && onChange(next)}>
	<Select.Trigger {id} class="w-full {className}" aria-label={t(domainMeta(domain).picker)} data-domain={domain}>
		{#if selected}
			<span class="flex min-w-0 items-center gap-2">
				<span class="size-2 shrink-0 rounded-full {selected.status === 'available' ? 'bg-success' : 'bg-warning'}" aria-hidden="true"></span>
				<span class="truncate">{selected.label}</span>
			</span>
		{:else}
			<span class="text-muted-foreground">{t('models.picker.empty')}</span>
		{/if}
	</Select.Trigger>
	<Select.Content>
		{#each models as model (model.id)}
			<Select.Item value={model.id} label={model.label}>
				<span class="flex items-center gap-2">
					<span class="size-2 shrink-0 rounded-full {model.status === 'available' ? 'bg-success' : 'bg-warning'}" aria-hidden="true"></span>
					{model.label}
					{#if model.status !== 'available'}<span class="text-muted-foreground text-xs">{t('models.picker.needsSetup')}</span>{/if}
				</span>
			</Select.Item>
		{/each}
	</Select.Content>
</Select.Root>
