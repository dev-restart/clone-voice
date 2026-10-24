<script module lang="ts">
	import { defineMeta } from '@storybook/addon-svelte-csf';

	const { Story } = defineMeta({ title: 'Foundations/Colors', parameters: { layout: 'padded' } });
	const groups = [
		{ title: 'Surface', tokens: ['background', 'card', 'muted', 'border', 'border-strong'] },
		{ title: 'Text', tokens: ['foreground', 'muted-foreground', 'subtle-foreground'] },
		{ title: 'Brand', tokens: ['primary', 'accent', 'accent-soft', 'ring'] },
		{ title: 'Status', tokens: ['success', 'success-soft', 'warning', 'warning-soft', 'danger', 'danger-soft'] }
	];
</script>

<Story name="Tokens">
	<div class="grid gap-6">
		{#each groups as group}
			<section>
				<h3 class="mb-2 text-sm font-semibold">{group.title}</h3>
				<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
					{#each group.tokens as token}
						<div class="border-border overflow-hidden rounded-lg border">
							<div class="h-14" style={`background: var(--${token})`}></div>
							<code class="block px-2 py-1.5 text-[11px]">--{token}</code>
						</div>
					{/each}
				</div>
			</section>
		{/each}
	</div>
</Story>
