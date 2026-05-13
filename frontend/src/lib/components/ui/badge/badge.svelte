<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '$lib/utils';

	type Variant = 'default' | 'secondary' | 'success' | 'warning' | 'danger';

	let {
		variant = 'default',
		class: className = '',
		children
	}: {
		variant?: Variant;
		class?: string;
		children?: Snippet;
	} = $props();

	const variants: Record<Variant, string> = {
		default: 'border-[color:var(--border)] bg-[var(--muted)] text-[color:var(--foreground)]',
		secondary: 'border-[color:var(--border)] bg-[var(--card)] text-[color:var(--muted-foreground)]',
		success: 'border-[color:var(--success-border)] bg-[var(--success-soft)] text-[color:var(--success)]',
		warning: 'border-[color:var(--warning-border)] bg-[var(--warning-soft)] text-[color:var(--warning)]',
		danger: 'border-[color:var(--danger-border)] bg-[var(--danger-soft)] text-[color:var(--danger)]'
	};
</script>

<span class={cn('inline-flex min-h-6 max-w-full items-center rounded-full border px-2.5 py-0.5 text-xs font-medium leading-tight', variants[variant], className)}>
	{@render children?.()}
</span>
