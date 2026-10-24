<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { MenuKey } from '$lib/studio/types';
	import MobileNav from './MobileNav.svelte';
	import SidebarNav from './SidebarNav.svelte';
	import Topbar from './Topbar.svelte';
	let {
		active,
		ready = true,
		showAuxiliaryTools = false,
		onNavigate,
		children
	}: {
		active: MenuKey;
		ready?: boolean;
		showAuxiliaryTools?: boolean;
		onNavigate: (key: MenuKey) => void;
		children?: Snippet;
	} = $props();
</script>

<main class="studio-shell">
	<SidebarNav {active} {ready} {showAuxiliaryTools} {onNavigate} />
	<section class="studio-main">
		<Topbar {active} />
		<MobileNav {active} {ready} {showAuxiliaryTools} {onNavigate} />
		<div class="studio-content">
			{@render children?.()}
		</div>
	</section>
</main>