<script module lang="ts">
	import { defineMeta } from '@storybook/addon-svelte-csf';
	import { Button } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
	import * as Popover from '$lib/components/ui/popover';
	import * as Tooltip from '$lib/components/ui/tooltip';

	const { Story } = defineMeta({ title: 'UI/Overlays', parameters: { layout: 'centered' } });
</script>

<Story name="Popover">
	<Popover.Root>
		<Popover.Trigger>{#snippet child({ props })}<Button variant="outline" {...props}>Open popover</Button>{/snippet}</Popover.Trigger>
		<Popover.Content class="w-64 text-xs">Use a popover for a hint that needs more than a few words.</Popover.Content>
	</Popover.Root>
</Story>

<Story name="Tooltip">
	<Tooltip.Provider>
		<Tooltip.Root>
			<Tooltip.Trigger>{#snippet child({ props })}<Button variant="outline" {...props}>Hover me</Button>{/snippet}</Tooltip.Trigger>
			<Tooltip.Content>Short label</Tooltip.Content>
		</Tooltip.Root>
	</Tooltip.Provider>
</Story>

<Story name="Dialog">
	<Dialog.Root>
		<Dialog.Trigger>{#snippet child({ props })}<Button {...props}>Delete script…</Button>{/snippet}</Dialog.Trigger>
		<Dialog.Content>
			<Dialog.Header>
				<Dialog.Title>Delete this script?</Dialog.Title>
				<Dialog.Description>Generated audio files stay in the File Library.</Dialog.Description>
			</Dialog.Header>
			<Dialog.Footer><Button variant="destructive">Delete</Button></Dialog.Footer>
		</Dialog.Content>
	</Dialog.Root>
</Story>

<Story name="Dropdown menu">
	<DropdownMenu.Root>
		<DropdownMenu.Trigger>{#snippet child({ props })}<Button variant="outline" {...props}>Project</Button>{/snippet}</DropdownMenu.Trigger>
		<DropdownMenu.Content class="min-w-48">
			<DropdownMenu.Item>Load latest saved version</DropdownMenu.Item>
			<DropdownMenu.Item variant="destructive">Delete project</DropdownMenu.Item>
		</DropdownMenu.Content>
	</DropdownMenu.Root>
</Story>
