import { AudioLines, Music2, AudioWaveform, Wand2 } from '@lucide/svelte';
import type { MessageKey } from '$lib/i18n/index.svelte';
import type { ModelDomain } from './types';

export type ModelDomainMeta = {
	domain: ModelDomain;
	icon: typeof AudioLines;
	label: MessageKey;
	help: MessageKey;
	picker: MessageKey;
};

export const modelDomainMeta: ModelDomainMeta[] = [
	{ domain: 'voice', icon: AudioLines, label: 'models.domain.voice', help: 'models.domain.voice.help', picker: 'models.domain.voice.picker' },
	{ domain: 'music', icon: Music2, label: 'models.domain.music', help: 'models.domain.music.help', picker: 'models.domain.music.picker' },
	{ domain: 'cover', icon: Wand2, label: 'models.domain.cover', help: 'models.domain.cover.help', picker: 'models.domain.cover.picker' },
	{ domain: 'sfx', icon: AudioWaveform, label: 'models.domain.sfx', help: 'models.domain.sfx.help', picker: 'models.domain.sfx.picker' }
];

export function domainMeta(domain: ModelDomain) {
	return modelDomainMeta.find((item) => item.domain === domain) ?? modelDomainMeta[0];
}
