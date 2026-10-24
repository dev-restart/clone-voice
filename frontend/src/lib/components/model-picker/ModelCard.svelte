<script lang="ts">
	import { ArrowDown, ArrowUp, Check, CheckCircle2, ChevronDown, Copy, ExternalLink, Loader2 } from '@lucide/svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import { Switch } from '$lib/components/ui/switch';
	import { t } from '$lib/i18n/index.svelte';
	import type { RuntimeModelStatus } from '$lib/studio/types';

	let {
		model,
		isDefault = false,
		enabled = true,
		canMoveUp = false,
		canMoveDown = false,
		loading = false,
		onToggle,
		onMakeDefault,
		onMove,
		onPreload
	}: {
		model: RuntimeModelStatus;
		isDefault?: boolean;
		enabled?: boolean;
		canMoveUp?: boolean;
		canMoveDown?: boolean;
		loading?: boolean;
		onToggle: (enabled: boolean) => void;
		onMakeDefault: () => void;
		onMove: (direction: 'up' | 'down') => void;
		onPreload: () => void;
	} = $props();

	const ready = $derived(model.status === 'available');
	let copied = $state(false);

	async function copyInstall() {
		if (!model.install_command) return;
		try {
			await navigator.clipboard.writeText(model.install_command);
			copied = true;
			setTimeout(() => (copied = false), 1600);
		} catch { /* Clipboard can be blocked; the command stays selectable on screen. */ }
	}
</script>

<li class="border-border-soft grid gap-2 border-t px-4 py-3.5 first:border-t-0 {enabled ? '' : 'bg-muted/30'}" data-model-id={model.id}>
	<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
		<div class="flex min-w-0 flex-1 items-center gap-3 {enabled ? '' : 'opacity-60'}">
			<span class="size-2 shrink-0 rounded-full {ready ? 'bg-success' : 'bg-warning'}" aria-hidden="true"></span>
			<div class="min-w-0">
				<div class="flex flex-wrap items-center gap-2">
					<strong class="text-sm">{model.label}</strong>
					{#if isDefault}<Badge variant="secondary">{t('models.default')}</Badge>{/if}
					<span class="text-xs font-semibold whitespace-nowrap {ready ? 'text-success' : 'text-warning'}">{ready ? t('common.ready') : t('common.needsSetup')}</span>
				</div>
				{#if model.recommended_for.length}
					<p class="text-muted-foreground mt-0.5 truncate text-xs">{model.recommended_for.join(' · ')}</p>
				{/if}
			</div>
		</div>
		<div class="flex items-center gap-2">
			<Button
				variant={isDefault ? 'secondary' : 'outline'}
				size="sm"
				disabled={!enabled || !ready || isDefault}
				onclick={onMakeDefault}
			>{isDefault ? t('models.default') : t('models.makeDefault')}</Button>
			<label class="text-muted-foreground flex cursor-pointer items-center gap-2 text-xs" title={enabled ? t('models.useTitleOn') : t('models.useTitleOff')}>
				<Switch size="sm" checked={enabled} onCheckedChange={onToggle} aria-label={model.label} />
				<span class="w-8">{enabled ? t('models.use') : t('models.hidden')}</span>
			</label>
		</div>
	</div>

	<details class="group">
		<summary class="text-muted-foreground hover:text-foreground flex w-fit cursor-pointer list-none items-center gap-1 text-xs [&::-webkit-details-marker]:hidden">
			<ChevronDown size={14} class="transition-transform group-open:rotate-180" aria-hidden="true" />{t('common.details')}
		</summary>
		<div class="grid gap-3 pt-3">
			<dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
				<div><dt class="text-subtle-foreground text-[11px]">{t('models.provider')}</dt><dd>{model.provider}</dd></div>
				<div><dt class="text-subtle-foreground text-[11px]">{t('models.device')}</dt><dd>{model.device ?? '-'}</dd></div>
				<div><dt class="text-subtle-foreground text-[11px]">{t('models.quality')}</dt><dd>{model.sample_rate / 1000}kHz</dd></div>
				<div><dt class="text-subtle-foreground text-[11px]">{t('models.memory')}</dt><dd>{model.loaded ? t('models.memoryLoaded') : t('models.memoryLazy')}</dd></div>
				{#if model.license}<div class="col-span-2"><dt class="text-subtle-foreground text-[11px]">{t('models.license')}</dt><dd>{model.license}</dd></div>{/if}
				{#if model.platforms?.length}<div class="col-span-2"><dt class="text-subtle-foreground text-[11px]">{t('models.platforms')}</dt><dd>{model.platforms.join(', ')}</dd></div>{/if}
			</dl>
			{#if model.message}<p class="text-muted-foreground text-xs leading-relaxed break-words">{model.message}</p>{/if}
			{#if !ready && model.install_command}
				<div class="bg-muted flex items-center justify-between gap-2 rounded-lg px-3 py-2">
					<code class="min-w-0 text-xs break-all" aria-label={t('models.install')}>{model.install_command}</code>
					<Button variant="ghost" size="xs" onclick={copyInstall}>
						{#if copied}<Check size={12} aria-hidden="true" />{t('models.copied')}{:else}<Copy size={12} aria-hidden="true" />{t('models.copy')}{/if}
					</Button>
				</div>
			{/if}
			<div class="flex flex-wrap items-center gap-2">
				<Button variant="outline" size="sm" disabled={loading || !ready} onclick={onPreload}>
					{#if loading}<Loader2 size={14} class="animate-spin" aria-hidden="true" />{:else}<CheckCircle2 size={14} aria-hidden="true" />{/if}{t('models.preload')}
				</Button>
				{#if model.homepage}
					<Button variant="ghost" size="sm" href={model.homepage} target="_blank" rel="noreferrer"><ExternalLink size={14} aria-hidden="true" />{t('models.homepage')}</Button>
				{/if}
				<span class="ml-auto inline-flex gap-1" role="group" aria-label={t('models.orderLabel', { name: model.label })}>
					<Button variant="ghost" size="icon-sm" disabled={!canMoveUp} onclick={() => onMove('up')} aria-label={t('models.moveUp', { name: model.label })}><ArrowUp size={14} aria-hidden="true" /></Button>
					<Button variant="ghost" size="icon-sm" disabled={!canMoveDown} onclick={() => onMove('down')} aria-label={t('models.moveDown', { name: model.label })}><ArrowDown size={14} aria-hidden="true" /></Button>
				</span>
			</div>
		</div>
	</details>
</li>
