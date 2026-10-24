<script module lang="ts">
	import { defineMeta } from '@storybook/addon-svelte-csf';
	import VoiceSampleInputPanel from '$lib/components/voice/VoiceSampleInputPanel.svelte';

	const { Story } = defineMeta({ title: 'Studio/Voice registration source', parameters: { layout: 'padded' } });
	const noop = () => {};
	const base = {
		recording: false, recordingSeconds: 0, mediaUrl: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', mediaTitle: '',
		isolateMediaVoice: true, busy: false, importingMedia: false, onFileChange: noop, onToggleRecord: noop,
		onMediaUrlChange: noop, onIsolateMediaVoiceChange: noop, onImportMedia: noop, onInspectMedia: noop, onClipChange: noop
	};
</script>

<Story name="Source tabs">
	<div class="w-full max-w-2xl"><VoiceSampleInputPanel {...base} /></div>
</Story>

<Story name="Imported audio">
	<div class="w-full max-w-2xl"><VoiceSampleInputPanel {...base} mediaTitle="Sample talk" /></div>
</Story>
