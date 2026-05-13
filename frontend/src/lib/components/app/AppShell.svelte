<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { MenuKey } from '$lib/studio/types';
	import MobileNav from './MobileNav.svelte';
	import SidebarNav from './SidebarNav.svelte';
	import Topbar from './Topbar.svelte';

	let {
		active,
		onNavigate,
		children
	}: {
		active: MenuKey;
		onNavigate: (key: MenuKey) => void;
		children?: Snippet;
	} = $props();
</script>

<main class="studio-shell">
	<SidebarNav {active} {onNavigate} />
	<section class="studio-main">
		<Topbar {active} />
		<MobileNav {active} {onNavigate} />
		<div class="studio-content">
			{@render children?.()}
		</div>
	</section>
</main>
