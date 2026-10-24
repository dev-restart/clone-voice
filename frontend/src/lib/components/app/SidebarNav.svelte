<script lang="ts">
	import { AudioWaveform } from '@lucide/svelte';
	import { t } from '$lib/i18n/index.svelte';
	import type { MenuKey } from '$lib/studio/types';
	import { studioMenus, mainMenuKey } from './navigation';

	let {
		active,
		ready = true,
		showAuxiliaryTools = false,
		onNavigate
	}: {
		active: MenuKey;
		ready?: boolean;
		showAuxiliaryTools?: boolean;
		onNavigate: (key: MenuKey) => void;
	} = $props();
	let menus = $derived(studioMenus.filter((item) => !item.auxiliary || showAuxiliaryTools));
</script>

<aside class="studio-sidebar">
	<div class="brand-row">
		<span class="brand-mark"><AudioWaveform size={21} strokeWidth={1.8} /></span>
		<span class="brand-copy">
			<strong>{t('app.name')}</strong>
			<small>{t('app.tagline')}</small>
		</span>
	</div>
	<nav class="nav-list" aria-label={t('nav.aria')}>
		{#each menus as item, index (item.key)}
			{#if item.groupKey && menus[index - 1]?.groupKey !== item.groupKey}
				<p class="nav-group">{t(item.groupKey)}</p>
			{/if}
			{@const Icon = item.icon}
			<button disabled={!ready} class:active={mainMenuKey(active) === item.key} aria-current={mainMenuKey(active) === item.key ? 'page' : undefined} onclick={() => onNavigate(item.key)}>
				<Icon size={19} />
				<span>{t(item.labelKey)}</span>
			</button>
		{/each}
	</nav>
</aside>
