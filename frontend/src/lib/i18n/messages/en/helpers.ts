import type { helpers } from '../ko/helpers.ts';

export const helpers_en: Record<keyof typeof helpers, string> = {
	'download.format': 'Choose MP3 or WAV.',
	'download.scope': 'Only audio stored in this app can be downloaded.',
	'download.path': 'Could not verify the audio file path.',
	'prod.kind.sound_effect': 'Sound-effect prompt',
	'prod.kind.music': 'Music draft',
	'prod.kind.song': 'Song & lyrics draft',
	'prod.kind.cover': 'Song cover settings',
	'ai.protocol.openai_chat': 'OpenAI-compatible · Chat Completions',
	'ai.protocol.anthropic_messages': 'Anthropic-compatible · Messages',
	'ai.protocol.openai_responses': 'OpenAI · Responses',
	'ai.task.translation': 'Translation',
	'ai.task.writing': 'Script writing & polishing',
	'ai.task.sound_prompt': 'Sound, music, song & cover help',
	'ai.preset.custom': 'Custom',
	'ai.preset.openai': 'OpenAI API · billed separately',
	'monitor.recovering': 'Restoring the live connection. Generation keeps running on the server.',
	'monitor.polling': 'The live connection is unavailable, so status is checked periodically.',
	'monitor.recoveringPoll': 'Restoring the live connection · using temporary status checks.',
	'monitor.offline': 'Check the server connection. Jobs are not resubmitted; waiting to reconnect.',
	'download.audio': 'audio',
	'download.formatLabel': '{name} download format',
	'download.action': 'Download {name} as {format}'
};
