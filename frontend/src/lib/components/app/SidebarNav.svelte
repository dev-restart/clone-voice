<script lang="ts">
	import type { MenuKey } from '$lib/studio/types';
	import { studioMenus } from './navigation';

	let {
		active,
		onNavigate
	}: {
		active: MenuKey;
		onNavigate: (key: MenuKey) => void;
	} = $props();
</script>

<aside class="studio-sidebar">
	<div class="brand-row">
		<div class="brand-wave"><span></span><span></span><span></span><span></span><span></span></div>
		<span class="brand-copy">
			<strong>Voice Studio</strong>
			<small>Clone Voice</small>
		</span>
	</div>
	<nav class="nav-list" aria-label="스튜디오 메뉴">
		{#each studioMenus as item, index (item.key)}
			{#if item.group && studioMenus[index - 1]?.group !== item.group}
				<p class="nav-group">{item.group}</p>
			{/if}
			{@const Icon = item.icon}
			<button class:active={active === item.key} aria-current={active === item.key ? 'page' : undefined} onclick={() => onNavigate(item.key)}>
				<Icon size={19} />
				<span>{item.label}</span>
			</button>
		{/each}
	</nav>
</aside>
