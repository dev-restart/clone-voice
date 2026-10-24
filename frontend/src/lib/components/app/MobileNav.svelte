<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import type { MenuKey } from '$lib/studio/types';
	import { studioMenus, mainMenuKey } from './navigation';

	let { active, ready = true, showAuxiliaryTools = false, onNavigate }: { active: MenuKey; ready?: boolean; showAuxiliaryTools?: boolean; onNavigate: (key: MenuKey) => void } = $props();
</script>

<nav class="studio-mobile-nav" aria-label={t('nav.ariaMobile')}>
	{#each studioMenus.filter((item) => !item.auxiliary || showAuxiliaryTools) as item (item.key)}
		<button disabled={!ready} class:active={mainMenuKey(active) === item.key} aria-current={mainMenuKey(active) === item.key ? 'page' : undefined} onclick={() => onNavigate(item.key)}>{t(item.labelKey)}</button>
	{/each}
</nav>
