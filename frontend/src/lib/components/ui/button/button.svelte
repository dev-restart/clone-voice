<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '$lib/utils';

	type Variant = 'default' | 'secondary' | 'outline' | 'ghost' | 'danger';
	type Size = 'default' | 'sm' | 'icon';

	let {
		variant = 'default',
		size = 'default',
		class: className = '',
		type = 'button',
		children,
		...rest
	}: {
		variant?: Variant;
		size?: Size;
		class?: string;
		type?: 'button' | 'submit' | 'reset';
		children?: Snippet;
		[key: string]: unknown;
	} = $props();

	const variants: Record<Variant, string> = {
		default:
			'border border-[color:var(--primary)] bg-[var(--primary)] text-[color:var(--primary-foreground)] shadow-[var(--shadow-button)] hover:bg-[var(--primary-hover)]',
		secondary:
			'border border-[color:var(--border)] bg-[var(--card)] text-[color:var(--foreground)] shadow-[var(--shadow-button)] hover:bg-[var(--muted)]',
		outline: 'border border-[color:var(--border-strong)] bg-transparent text-[color:var(--foreground)] hover:bg-[var(--muted)]',
		ghost: 'border border-transparent bg-transparent text-[color:var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[color:var(--foreground)]',
		danger:
			'border border-[color:var(--danger-border)] bg-[var(--danger-soft)] text-[color:var(--danger)] hover:bg-[var(--danger-hover)]'
	};

	const sizes: Record<Size, string> = {
		default: 'min-h-9 px-3.5 py-2 text-sm',
		sm: 'min-h-8 px-3 py-1.5 text-xs',
		icon: 'size-8 p-0'
	};
</script>

<button
	data-ui="button"
	{type}
	class={cn(
		'inline-flex items-center justify-center gap-2 rounded-[var(--radius-sm)] font-medium leading-none transition disabled:pointer-events-none disabled:opacity-50',
		'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]',
		'whitespace-normal text-center',
		variants[variant],
		sizes[size],
		className
	)}
	{...rest}
>
	{@render children?.()}
</button>
