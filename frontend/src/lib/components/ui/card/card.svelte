<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '$lib/utils';

	let { class: className = '', children }: { class?: string; children?: Snippet } = $props();
</script>

<section class={cn('rounded-[var(--radius-lg)] border border-[color:var(--border)] bg-[var(--card)] text-[color:var(--foreground)] shadow-[var(--shadow-card)]', className)}>
	{@render children?.()}
</section>
