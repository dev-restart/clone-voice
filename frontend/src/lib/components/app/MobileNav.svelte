<script lang="ts">
	import type { MenuKey } from '$lib/studio/types';
	import { studioMenus } from './navigation';

	let { active, onNavigate }: { active: MenuKey; onNavigate: (key: MenuKey) => void } = $props();
</script>

<div class="studio-mobile-nav">
	{#each studioMenus as item}
		<button class:active={active === item.key} onclick={() => onNavigate(item.key)}>{item.label}</button>
	{/each}
</div>
