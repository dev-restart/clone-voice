<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { MenuKey } from '$lib/studio/types';
	import AppShell from './app/AppShell.svelte';

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

<AppShell {active} {onNavigate}>
	{@render children?.()}
</AppShell>
