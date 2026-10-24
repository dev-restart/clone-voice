<script module lang="ts">
	import { defineMeta } from '@storybook/addon-svelte-csf';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import * as RadioGroup from '$lib/components/ui/radio-group';
	import * as Select from '$lib/components/ui/select';
	import { Slider } from '$lib/components/ui/slider';
	import { Switch } from '$lib/components/ui/switch';
	import { Textarea } from '$lib/components/ui/textarea';

	const { Story } = defineMeta({ title: 'UI/Form controls', parameters: { layout: 'padded' } });
	let voice = $state('mine');
	let speed = $state([1]);
</script>

<Story name="Text">
	<div class="grid max-w-sm gap-4">
		<div class="grid gap-1.5"><Label for="title">Title</Label><Input id="title" placeholder="Short video intro" /></div>
		<div class="grid gap-1.5"><Label for="script">Script</Label><Textarea id="script" rows={4} placeholder="Write something to say…" /></div>
	</div>
</Story>

<Story name="Choice">
	<div class="grid max-w-sm gap-5">
		<div class="flex items-center gap-2"><Switch id="normalize" checked /><Label for="normalize">Even out volume</Label></div>
		<div class="flex items-center gap-2"><Checkbox id="optional" /><Label for="optional">Re-translate existing translations</Label></div>
		<RadioGroup.Root value="balanced" class="grid gap-2">
			{#each ['fast', 'balanced', 'high'] as quality}
				<div class="flex items-center gap-2"><RadioGroup.Item value={quality} id={quality} /><Label for={quality} class="capitalize">{quality}</Label></div>
			{/each}
		</RadioGroup.Root>
		<div class="grid gap-2">
			<Label>Speed {speed[0].toFixed(2)}×</Label>
			<Slider type="multiple" bind:value={speed} min={0.5} max={2} step={0.05} />
		</div>
		<div class="grid gap-1.5">
			<Label>Voice</Label>
			<Select.Root type="single" bind:value={voice}>
				<Select.Trigger class="w-full">{voice === 'mine' ? 'My voice' : 'Default voice'}</Select.Trigger>
				<Select.Content>
					<Select.Item value="mine">My voice</Select.Item>
					<Select.Item value="default">Default voice</Select.Item>
				</Select.Content>
			</Select.Root>
		</div>
	</div>
</Story>
