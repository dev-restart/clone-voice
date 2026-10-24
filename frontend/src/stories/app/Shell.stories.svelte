<script module lang="ts">
	import { defineMeta } from '@storybook/addon-svelte-csf';
	import HelpPopover from '$lib/components/HelpPopover.svelte';
	import LanguageSwitcher from '$lib/components/app/LanguageSwitcher.svelte';
	import ProgressPanel from '$lib/components/app/ProgressPanel.svelte';
	import TtsTemplatePicker from '$lib/components/tts/TtsTemplatePicker.svelte';

	const { Story } = defineMeta({ title: 'Studio/Shell & hints', parameters: { layout: 'padded' } });
</script>

<Story name="Help popover (?)">
	<p class="text-sm">
		Quality
		<HelpPopover label="Quality" text="Fast is for drafts. High takes longer and is best for the final audio." />
	</p>
</Story>

<Story name="Language switcher">
	<LanguageSwitcher />
</Story>

<Story name="Progress">
	<div class="w-96"><ProgressPanel progress={{ percent: 42, message: 'Generating speech…', elapsed: 12, active: true }} /></div>
</Story>

<Story name="Starter templates">
	<div class="w-full max-w-4xl"><TtsTemplatePicker onSelect={() => {}} /></div>
</Story>
