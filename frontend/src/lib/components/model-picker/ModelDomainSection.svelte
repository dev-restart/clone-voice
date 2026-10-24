<script lang="ts">
	import { BookOpen } from '@lucide/svelte';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import { t } from '$lib/i18n/index.svelte';
	import { ADD_MODEL_GUIDE_URL } from '$lib/studio/links';
	import type { ModelDomainMeta } from '$lib/studio/model-domains';
	import type { RuntimeModelStatus } from '$lib/studio/types';
	import ModelCard from './ModelCard.svelte';

	let {
		meta,
		models,
		defaultId = '',
		isEnabled,
		loadingId = '',
		onToggle,
		onMakeDefault,
		onMove,
		onPreload
	}: {
		meta: ModelDomainMeta;
		models: RuntimeModelStatus[];
		defaultId?: string;
		isEnabled: (modelId: string) => boolean;
		loadingId?: string;
		onToggle: (modelId: string, enabled: boolean) => void;
		onMakeDefault: (modelId: string) => void;
		onMove: (modelId: string, direction: 'up' | 'down') => void;
		onPreload: (model: RuntimeModelStatus) => void;
	} = $props();

	const Icon = $derived(meta.icon);
	const headingId = $derived(`models-${meta.domain}`);
</script>

<section class="grid gap-3" aria-labelledby={headingId} data-domain={meta.domain}>
	<div class="flex items-center gap-2">
		<Icon size={18} class="text-brand" aria-hidden="true" />
		<h3 id={headingId} class="text-base font-semibold">{t(meta.label)}</h3>
		<Badge variant="secondary">{t('models.count', { count: models.length })}</Badge>
		<HelpPopover label={t(meta.label)} text={t(meta.help)} />
	</div>

	{#if models.length}
		<ul class="border-border bg-card m-0 grid list-none rounded-xl border p-0">
			{#each models as model, index (model.id)}
				<ModelCard
					{model}
					isDefault={defaultId === model.id}
					enabled={isEnabled(model.id)}
					canMoveUp={index > 0}
					canMoveDown={index < models.length - 1}
					loading={loadingId === model.id}
					onToggle={(next) => onToggle(model.id, next)}
					onMakeDefault={() => onMakeDefault(model.id)}
					onMove={(direction) => onMove(model.id, direction)}
					onPreload={() => onPreload(model)}
				/>
			{/each}
		</ul>
	{:else}
		<div class="border-border bg-card/50 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed px-4 py-5">
			<div>
				<p class="text-sm font-medium">{t('models.empty.title', { domain: t(meta.label) })}</p>
				<p class="text-muted-foreground mt-0.5 text-xs">{t('models.empty.hint')}</p>
			</div>
			<Button variant="outline" size="sm" href={ADD_MODEL_GUIDE_URL} target="_blank" rel="noreferrer"><BookOpen size={14} aria-hidden="true" />{t('models.empty.guide')}</Button>
		</div>
	{/if}
</section>
