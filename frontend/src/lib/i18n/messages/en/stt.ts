import type { stt } from '../ko/stt.ts';

export const stt_en: Record<keyof typeof stt, string> = {
	'stt.settings': 'Transcription & translation settings',
	'stt.settingsHelp': 'Knowing the source language improves accuracy; the result can be translated into the languages you pick.',
	'stt.engine': 'Recognition engine',
	'stt.auto': 'Auto-detect',
	'stt.targets': 'Translate into',
	'stt.targetsHelp': 'You can pick several languages at once.',
	'stt.translate': 'Translate into selected languages',
	'stt.translateFirst': 'Transcribe first, then translate',
	'stt.title': 'Turn speech into text',
	'stt.start': 'Start transcribing',
	'stt.stepsLabel': 'Transcription steps',
	'stt.step1': '1. Choose audio',
	'stt.step2': '2. Check the text',
	'stt.step3': '3. Translate',
	'stt.pick': 'Choose an audio file or record now',
	'stt.formats': 'WAV, MP3, M4A, WebM',
	'stt.result': 'Transcript',
	'stt.hasResult': 'Ready',
	'stt.waiting': 'Waiting',
	'stt.placeholder': 'The transcript shows up here. Edit it if needed.',
	'stt.translations': 'Translations',
	'stt.recordFail': 'Could not start recording.',
	'stt.needFile': 'Choose an audio file to transcribe.',
	'stt.done': 'Transcribed the audio.',
	'stt.translated': 'Translation finished.'
};
