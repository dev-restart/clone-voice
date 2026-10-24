<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { MenuKey } from '$lib/studio/types';
	import AppShell from './app/AppShell.svelte';

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

<AppShell {active} {ready} {showAuxiliaryTools} {onNavigate}>
	{@render children?.()}
</AppShell>