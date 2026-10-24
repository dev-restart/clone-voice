<script module lang="ts">
	import { defineMeta } from '@storybook/addon-svelte-csf';
	import { Badge } from '$lib/components/ui/badge';

	const { Story } = defineMeta({
		title: 'UI/Badge',
		component: Badge,
		argTypes: { variant: { control: 'select', options: ['default', 'secondary', 'outline', 'success', 'warning', 'danger'] } }
	});
</script>

<Story name="Status" parameters={{ controls: { disable: true } }}>
	<div class="flex flex-wrap items-center gap-2">
		<Badge variant="success">Ready</Badge>
		<Badge variant="warning">Setup needed</Badge>
		<Badge variant="danger">Failed</Badge>
		<Badge variant="secondary">Default</Badge>
		<Badge variant="outline">Optional</Badge>
	</div>
</Story>
