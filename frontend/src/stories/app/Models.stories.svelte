<script module lang="ts">
	import { defineMeta } from '@storybook/addon-svelte-csf';
	import ModelCard from '$lib/components/model-picker/ModelCard.svelte';
	import ModelDomainSection from '$lib/components/model-picker/ModelDomainSection.svelte';
	import ModelPicker from '$lib/components/model-picker/ModelPicker.svelte';
	import { modelDomainMeta } from '$lib/studio/model-domains';
	import type { RuntimeModelStatus } from '$lib/studio/types';

	const base = { provider: 'OpenBMB', enabled: true, loaded: false, sample_rate: 48000, recommended_for: ['48kHz TTS', '30 languages'], message: null };
	const caps = { tts: true, voice_clone_tts: true, voice_design: false, stt: false, voice_conversion: false };
	const ready: RuntimeModelStatus = { ...base, id: 'voxcpm', label: 'VoxCPM2', status: 'available', capabilities: caps, license: 'Apache-2.0', platforms: ['macOS', 'Linux'], homepage: 'https://github.com/OpenBMB/VoxCPM', device: 'mps' };
	const missing: RuntimeModelStatus = { ...ready, id: 'next-voice', label: 'Next voice model', status: 'unavailable', message: 'Model weights were not found.', install_command: './download-models.sh --tts' };

	const { Story } = defineMeta({ title: 'Studio/Models', parameters: { layout: 'padded' } });
	const noop = () => {};
</script>

<Story name="Picker">
	<div class="w-72"><ModelPicker models={[ready, missing]} value="voxcpm" domain="voice" onChange={noop} /></div>
</Story>

<Story name="Card ready">
	<ul class="border-border bg-card m-0 w-full max-w-2xl list-none rounded-xl border p-0">
		<ModelCard model={ready} isDefault enabled onToggle={noop} onMakeDefault={noop} onMove={noop} onPreload={noop} />
	</ul>
</Story>

<Story name="Card needs setup">
	<ul class="border-border bg-card m-0 w-full max-w-2xl list-none rounded-xl border p-0">
		<ModelCard model={missing} enabled onToggle={noop} onMakeDefault={noop} onMove={noop} onPreload={noop} />
	</ul>
</Story>

<Story name="Domain section">
	<div class="w-full max-w-2xl">
		<ModelDomainSection meta={modelDomainMeta[0]} models={[ready, missing]} defaultId="voxcpm" isEnabled={() => true} onToggle={noop} onMakeDefault={noop} onMove={noop} onPreload={noop} />
	</div>
</Story>

<Story name="Domain section empty">
	<div class="w-full max-w-2xl">
		<ModelDomainSection meta={modelDomainMeta[1]} models={[]} isEnabled={() => true} onToggle={noop} onMakeDefault={noop} onMove={noop} onPreload={noop} />
	</div>
</Story>
