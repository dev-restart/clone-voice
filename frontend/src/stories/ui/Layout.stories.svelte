<script module lang="ts">
	import { defineMeta } from '@storybook/addon-svelte-csf';
	import * as Alert from '$lib/components/ui/alert';
	import * as Card from '$lib/components/ui/card';
	import { Progress } from '$lib/components/ui/progress';
	import { Separator } from '$lib/components/ui/separator';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import * as Tabs from '$lib/components/ui/tabs';

	const { Story } = defineMeta({ title: 'UI/Layout & feedback', parameters: { layout: 'padded' } });
</script>

<Story name="Card">
	<Card.Root class="max-w-sm">
		<Card.Header><Card.Title>Short video</Card.Title><Card.Description>A short story that hooks in the first sentence</Card.Description></Card.Header>
		<Card.Content class="text-sm">Shorts · Reels</Card.Content>
	</Card.Root>
</Story>

<Story name="Tabs">
	<Tabs.Root value="models" class="max-w-md">
		<Tabs.List><Tabs.Trigger value="general">General</Tabs.Trigger><Tabs.Trigger value="models">Models</Tabs.Trigger><Tabs.Trigger value="ai">AI connections</Tabs.Trigger></Tabs.List>
		<Tabs.Content value="models" class="text-sm">Pick a default model per area.</Tabs.Content>
	</Tabs.Root>
</Story>

<Story name="Alert & progress">
	<div class="grid max-w-md gap-4">
		<Alert.Root><Alert.Title>Heads up</Alert.Title><Alert.Description>The model is loading for the first time.</Alert.Description></Alert.Root>
		<Alert.Root variant="destructive"><Alert.Title>Could not generate</Alert.Title><Alert.Description>The speech model is not installed.</Alert.Description></Alert.Root>
		<Progress value={62} />
		<Separator />
		<Skeleton class="h-10 w-full" />
	</div>
</Story>
