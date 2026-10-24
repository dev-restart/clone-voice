<script module lang="ts">
	import { defineMeta } from '@storybook/addon-svelte-csf';
	import { Download, Plus } from '@lucide/svelte';
	import { Button } from '$lib/components/ui/button';

	const { Story } = defineMeta({
		title: 'UI/Button',
		component: Button,
		argTypes: {
			variant: { control: 'select', options: ['default', 'secondary', 'outline', 'ghost', 'destructive', 'link'] },
			size: { control: 'select', options: ['default', 'xs', 'sm', 'lg', 'icon', 'icon-sm'] },
			disabled: { control: 'boolean' }
		},
		args: { variant: 'default', size: 'default', disabled: false }
	});
</script>

<Story name="Playground">
	{#snippet template(args)}<Button {...args}>Generate speech</Button>{/snippet}
</Story>

<Story name="Variants" parameters={{ controls: { disable: true } }}>
	<div class="flex flex-wrap items-center gap-3">
		<Button>Primary</Button>
		<Button variant="secondary">Secondary</Button>
		<Button variant="outline">Outline</Button>
		<Button variant="ghost">Ghost</Button>
		<Button variant="destructive">Delete</Button>
		<Button variant="link">Link</Button>
	</div>
</Story>

<Story name="With icon" parameters={{ controls: { disable: true } }}>
	<div class="flex flex-wrap items-center gap-3">
		<Button><Plus size={16} />New script</Button>
		<Button variant="secondary"><Download size={16} />Download MP3</Button>
		<Button variant="outline" size="icon" aria-label="Add"><Plus size={16} /></Button>
	</div>
</Story>
