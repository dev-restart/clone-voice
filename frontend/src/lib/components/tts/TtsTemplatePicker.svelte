<script lang="ts">
	import { ArrowUpRight, Clapperboard, GraduationCap, Megaphone, MonitorPlay } from '@lucide/svelte';
	import { t } from '$lib/i18n/index.svelte';
	import { getProductionTemplates, type ProductionTemplate } from '$lib/studio/production';
	let { onSelect }: { onSelect: (template: ProductionTemplate) => void } = $props();
	const icons = [Clapperboard, GraduationCap, MonitorPlay, Megaphone];
	const templates = $derived(getProductionTemplates());
</script>

<div class="production-templates" aria-label={t('tts.templates.aria')}>
	{#each templates as template, index (template.id)}
		{@const Icon = icons[index]}
		<button class="production-template" onclick={() => onSelect(template)}>
			<span class="template-icon"><Icon size={23} strokeWidth={1.6} /></span>
			<span class="template-use">{template.use}</span>
			<strong>{template.title}</strong>
			<span class="template-description">{template.description}</span>
			<ArrowUpRight class="template-start" size={16} aria-hidden="true" />
		</button>
	{/each}
</div>
